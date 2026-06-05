"""Create an Azure Data Factory high-cost test pipeline with sample ADLS Gen2 data.

This script is focused on resource provisioning and does not configure Azure Monitor Diagnostic Settings,
Cost Management exports, or billing alerts. Those are separate Azure configurations and must be added
via Azure Monitor / Diagnostic Settings or an ARM/Bicep deployment if required.
"""

from azure.identity import DefaultAzureCredential
from azure.mgmt.datafactory import DataFactoryManagementClient
from azure.storage.filedatalake import DataLakeServiceClient
from azure.core.exceptions import ResourceExistsError
from azure.mgmt.datafactory import models as adf_models

import json
import pandas as pd
import random
import sys

# ============================================================
# CONFIGURATION SECTION
# ============================================================
# Update these values to match your Azure subscription, resource group,
# Data Factory, and ADLS Gen2 storage account.
SUBSCRIPTION_ID = "y57f5e225-b0f9-4d69-8b57-b73af00b3f07"
RESOURCE_GROUP = "rg_datafactories"
ADF_NAME = "ADF-DatatloadTest2"
STORAGE_ACCOUNT_NAME = "strgadfcostopt"

RAW_CONTAINER = "raw"
PROCESSED_CONTAINER = "processed"
SALES_FOLDER = "sales"
CSV_FILENAME = "large_sales_data.csv"

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def authenticate() -> DefaultAzureCredential:
    """Authenticate using DefaultAzureCredential."""
    print("Authenticating...")
    return DefaultAzureCredential()


def create_datafactory_client(credential: DefaultAzureCredential) -> DataFactoryManagementClient:
    """Create and return the Azure Data Factory management client."""
    return DataFactoryManagementClient(credential, SUBSCRIPTION_ID)


def verify_data_factory_exists(client: DataFactoryManagementClient) -> None:
    """Verify the Data Factory exists and exit if it is missing."""
    try:
        factory = client.factories.get(RESOURCE_GROUP, ADF_NAME)
        print(f"ADF Found: {factory.name}")
    except Exception as exc:
        print("ADF NOT FOUND")
        print(exc)
        sys.exit(1)


def create_adls_client(credential: DefaultAzureCredential) -> DataLakeServiceClient:
    """Create the ADLS Gen2 DataLakeServiceClient for file system operations."""
    account_url = f"https://{STORAGE_ACCOUNT_NAME}.dfs.core.windows.net"
    client = DataLakeServiceClient(account_url=account_url, credential=credential)
    print("Connected to ADLS")
    return client


def ensure_containers_exist(service_client: DataLakeServiceClient) -> None:
    """Create required ADLS containers if they do not already exist."""
    for container in [RAW_CONTAINER, PROCESSED_CONTAINER]:
        try:
            service_client.create_file_system(container)
            print(f"Created Container: {container}")
        except ResourceExistsError:
            print(f"Container Exists: {container}")


def generate_large_dataset(rows: int = 3_000_000) -> str:
    """Generate a large Pandas DataFrame and return its CSV text."""
    print("Generating large dataset...")
    countries = ["IN", "US", "UK", "UAE", "SG"]
    products = ["Laptop", "Phone", "TV", "Watch", "Tablet"]

    large_df = pd.DataFrame({
        "id": range(rows),
        "customer": [f"Customer_{i}" for i in range(rows)],
        "country": [random.choice(countries) for _ in range(rows)],
        "product": [random.choice(products) for _ in range(rows)],
        "amount": [random.randint(1000, 50000) for _ in range(rows)],
        "discount": [random.randint(1, 30) for _ in range(rows)],
        "quantity": [random.randint(1, 10) for _ in range(rows)],
    })

    csv_text = large_df.to_csv(index=False)
    print("Dataset Generated")
    print(f"Approx Dataset Size MB: {round(len(csv_text) / 1024 / 1024, 2)}")
    return csv_text


def upload_csv_to_adls(service_client: DataLakeServiceClient, csv_text: str) -> None:
    """Upload the CSV text to ADLS Gen2 using chunked append/flush to avoid timeout issues."""
    print("Uploading file to ADLS...")
    raw_fs_client = service_client.get_file_system_client(RAW_CONTAINER)
    try:
        raw_fs_client.create_directory(SALES_FOLDER)
    except Exception:
        pass

    file_client = raw_fs_client.get_file_client(f"{SALES_FOLDER}/{CSV_FILENAME}")
    data_bytes = csv_text.encode("utf-8")

    try:
        file_client.create_file()
    except Exception:
        pass

    chunk_size = 4 * 1024 * 1024
    offset = 0
    for i in range(0, len(data_bytes), chunk_size):
        chunk = data_bytes[i : i + chunk_size]
        file_client.append_data(chunk, offset=offset)
        offset += len(chunk)

    file_client.flush_data(offset)
    print("Large CSV Uploaded")


def create_linked_service(client: DataFactoryManagementClient) -> str:
    """Create the Data Factory linked service pointing to ADLS Gen2."""
    linked_service_name = "LS_ADLS_GEN2"
    linked_service_payload = {
        "properties": {
            "type": "AzureBlobFS",
            "typeProperties": {"url": f"https://{STORAGE_ACCOUNT_NAME}.dfs.core.windows.net"},
        }
    }
    print("Creating Linked Service...")
    client.linked_services.create_or_update(
        RESOURCE_GROUP, ADF_NAME, linked_service_name, linked_service_payload
    )
    print("Linked Service Created")
    return linked_service_name


def create_delimited_dataset(client: DataFactoryManagementClient, dataset_name: str, file_system: str, file_name: str, folder_path: str) -> None:
    """Create a delimited text dataset in Azure Data Factory."""
    payload = {
        "properties": {
            "linkedServiceName": {"referenceName": "LS_ADLS_GEN2", "type": "LinkedServiceReference"},
            "type": "DelimitedText",
            "typeProperties": {
                "location": {
                    "type": "AzureBlobFSLocation",
                    "fileName": file_name,
                    "folderPath": folder_path,
                    "fileSystem": file_system,
                },
                "columnDelimiter": ",",
                "firstRowAsHeader": True,
            },
            "schema": [],
        }
    }
    print(f"Creating dataset: {dataset_name}...")
    client.datasets.create_or_update(RESOURCE_GROUP, ADF_NAME, dataset_name, payload)
    print(f"Dataset created: {dataset_name}")


def build_high_cost_pipeline(source_dataset_name: str, sink_dataset_name: str) -> adf_models.PipelineResource:
    """Build a high-cost pipeline using SDK models for safe serialization."""
    copy_activity = adf_models.CopyActivity(
        name="Heavy_Copy",
        source=adf_models.DelimitedTextSource(),
        sink=adf_models.DelimitedTextSink(),
        inputs=[adf_models.DatasetReference(type="DatasetReference", reference_name=source_dataset_name)],
        outputs=[adf_models.DatasetReference(type="DatasetReference", reference_name=sink_dataset_name)],
        policy=adf_models.ActivityPolicy(
            timeout={"value": "7.00:00:00"}, retry={"value": 5}, retry_interval_in_seconds=30
        ),
        enable_staging={"value": True},
        parallel_copies={"value": 32},
    )
    wait_activity = adf_models.WaitActivity(name="Wait_120_Seconds", wait_time_in_seconds={"value": 120})
    for_each = adf_models.ForEachActivity(
        name="ForEach_Heavy_Load",
        items=adf_models.Expression(type=adf_models.ExpressionType.EXPRESSION, value=json.dumps(list(range(1, 11)))),
        activities=[copy_activity, wait_activity],
        is_sequential=False,
    )
    return adf_models.PipelineResource(activities=[for_each])


def create_high_cost_pipeline(client: DataFactoryManagementClient, pipeline_resource: adf_models.PipelineResource) -> None:
    """Deploy the high-cost Azure Data Factory pipeline."""
    pipeline_name = "PL_HIGH_COST_TEST"
    print("Creating High Cost Pipeline...")
    client.pipelines.create_or_update(RESOURCE_GROUP, ADF_NAME, pipeline_name, pipeline_resource)
    print("High Cost Pipeline Created")


def main() -> None:
    """Main entrypoint for the provisioning script."""
    credential = authenticate()
    adf_client = create_datafactory_client(credential)
    verify_data_factory_exists(adf_client)
    adls_client = create_adls_client(credential)
    ensure_containers_exist(adls_client)

    csv_text = generate_large_dataset()
    upload_csv_to_adls(adls_client, csv_text)

    linked_service_name = create_linked_service(adf_client)
    create_delimited_dataset(adf_client, "DS_LARGE_SOURCE", RAW_CONTAINER, CSV_FILENAME, SALES_FOLDER)
    create_delimited_dataset(adf_client, "DS_LARGE_SINK", PROCESSED_CONTAINER, "", "output")

    pipeline_resource = build_high_cost_pipeline("DS_LARGE_SOURCE", "DS_LARGE_SINK")
    create_high_cost_pipeline(adf_client, pipeline_resource)

    print("\nDONE")


if __name__ == "__main__":
    main()

