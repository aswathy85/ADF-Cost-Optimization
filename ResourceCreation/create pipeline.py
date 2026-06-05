from azure.identity import DefaultAzureCredential
from azure.mgmt.datafactory import DataFactoryManagementClient
from azure.storage.filedatalake import DataLakeServiceClient
from azure.core.exceptions import ResourceExistsError
import sys

"""
============================================================
ADF COST OPTIMIZATION PROJECT
AUTOMATED ENVIRONMENT PROVISIONING FRAMEWORK
============================================================

WHAT THIS SCRIPT DOES
------------------------------------------------------------
1. Connects to Azure subscription
2. Creates ADLS Gen2 containers
3. Uploads sample CSV data
4. Creates ADF Linked Services
5. Creates ADF Datasets
6. Creates 2 Pipelines
    - Bad costly pipeline
    - Optimized pipeline

PRE-REQUISITES
------------------------------------------------------------
1. Resource Group already created
2. Azure Data Factory already created
3. Storage Account already created with HNS enabled
4. Python installed
5. Azure CLI installed
6. Logged into Azure using:

    az login

INSTALL REQUIRED PACKAGES
------------------------------------------------------------

pip install azure-identity
pip install azure-mgmt-storage
pip install azure-mgmt-datafactory
pip install azure-storage-file-datalake

============================================================
CONFIGURATION SECTION
============================================================
"""

# ============================================================
# UPDATE THESE VALUES
# ============================================================

SUBSCRIPTION_ID = "57f5e225-b0f9-4d69-8b57-b73af00b3f07"
RESOURCE_GROUP = "rg_datafactories"
LOCATION = "eastus"

ADF_NAME = "ADF-DataLoadTest1"
STORAGE_ACCOUNT_NAME = "strgadfcostopt"

# ============================================================
# CONTAINERS TO CREATE
# ============================================================

CONTAINERS = [
    "raw",
    "processed",
    "logs"
]

# Sample CSV used for provisioning tests
SAMPLE_CSV = """id,customer,amount,country,last_updated
1,Alice,100,US,2026-01-01
2,Bob,250,UK,2026-01-02
3,John,175,IN,2026-01-03
4,Ravi,450,IN,2026-01-04
5,Sarah,300,US,2026-01-05
"""
print("Authenticating with Azure...")
credential = DefaultAzureCredential()

# ============================================================
# STORAGE CLIENTS
# ============================================================

# Storage management client not required by this provisioning script.

# ============================================================
# DATA FACTORY CLIENT
# ============================================================

datafactory_client = DataFactoryManagementClient(
    credential,
    SUBSCRIPTION_ID
)

# Verify the Data Factory exists to fail fast with a clear message
try:
    factory = datafactory_client.factories.get(RESOURCE_GROUP, ADF_NAME)
    print(f"Found Data Factory: {factory.name}")
except Exception as e:
    print(f"Unable to find Data Factory '{ADF_NAME}' in resource group '{RESOURCE_GROUP}': {e}")
    sys.exit(1)

# ============================================================
# CREATE ADLS CONNECTION STRING
# ============================================================

account_url = f"https://{STORAGE_ACCOUNT_NAME}.dfs.core.windows.net"

service_client = DataLakeServiceClient(
    account_url=account_url,
    credential=credential
)

print("Connected to ADLS Gen2")

# Track created/available components
created_components = set()

# ============================================================
# CREATE CONTAINERS
# ============================================================

# Create ADLS containers. If a container already exists we skip creation —
# the script is safe to re-run and will not recreate existing resources.
print("Creating ADLS containers...")

for container in CONTAINERS:
    try:
        file_system_client = service_client.create_file_system(container)
        print(f"Container created: {container}")
        created_components.add("ADLS Containers")
    except ResourceExistsError:
        # Already exists: nothing to do.
        print(f"Container already exists: {container}")
        created_components.add("ADLS Containers")

# ============================================================
# UPLOAD SAMPLE CSV FILE
# ============================================================


# Upload sample CSV file. We use overwrite=True so repeated runs replace the
# sample data without failing — safe for idempotent provisioning.
print("Uploading sample CSV file...")

raw_fs_client = service_client.get_file_system_client("raw")

# Create directory
try:
    raw_fs_client.create_directory("sales")
except Exception as e:
    print(f"Warning creating ADLS directory 'sales': {e}")

# Create file
file_client = raw_fs_client.get_file_client("sales/sales_data.csv")


# Write or overwrite the sample CSV file in the 'raw' filesystem.
file_client.upload_data(
    SAMPLE_CSV,
    overwrite=True
)

print("Sample CSV uploaded successfully")
created_components.add("Sample CSV")

# ============================================================
# CREATE LINKED SERVICE
# ============================================================

print("Creating ADF linked service...")

linked_service_name = "LS_ADLS_GEN2"

linked_service_payload = {
    "properties": {
        "type": "AzureBlobFS",
        "typeProperties": {
            "url": f"https://{STORAGE_ACCOUNT_NAME}.dfs.core.windows.net"
        },
    }
}

# First check if linked service already exists; if so, skip creation.
try:
    existing = datafactory_client.linked_services.get(RESOURCE_GROUP, ADF_NAME, linked_service_name)
    if existing:
        print(f"Linked service already present: {linked_service_name}")
        created_components.add("Linked Service")
except Exception as e:
    # An error occurred checking existence — log and attempt creation
    print(f"Linked service check error (will attempt create): {e}")
    try:
        result = datafactory_client.linked_services.create_or_update(
            RESOURCE_GROUP,
            ADF_NAME,
            linked_service_name,
            linked_service_payload
        )

        print("Linked service created:", getattr(result, 'name', result))
        created_components.add("Linked Service")
    except Exception as e:
        print(f"Linked service error: {e}")

# ============================================================
# CREATE SOURCE DATASET
# ============================================================

print("Creating source dataset...")

source_dataset_name = "DS_Sales_CSV"

source_dataset_payload = {
    "properties": {
        "linkedServiceName": {
            "referenceName": linked_service_name,
            "type": "LinkedServiceReference"
        },
        "type": "DelimitedText",
        "typeProperties": {
            "location": {
                "type": "AzureBlobFSLocation",
                "fileName": "sales_data.csv",
                "folderPath": "sales",
                "fileSystem": "raw"
            },
            "columnDelimiter": ",",
            "firstRowAsHeader": True
        },
        "schema": []
    }
}

try:
    # Check if source dataset exists; if not, create it.
    existing = datafactory_client.datasets.get(RESOURCE_GROUP, ADF_NAME, source_dataset_name)
    if existing:
        print(f"Source dataset already present: {source_dataset_name}")
        created_components.add("Source Dataset")
except Exception as e:
    # Not found or error checking — attempt to create
    print(f"Source dataset check error (will attempt create): {e}")
    try:
        result = datafactory_client.datasets.create_or_update(
            RESOURCE_GROUP,
            ADF_NAME,
            source_dataset_name,
            source_dataset_payload
        )

        print("Source dataset created:", getattr(result, 'name', result))
        created_components.add("Source Dataset")
    except Exception as e:
        print(f"Dataset error: {e}")

# ============================================================
# CREATE SINK DATASET
# ============================================================

print("Creating sink dataset...")

sink_dataset_name = "DS_Sales_Output"

sink_dataset_payload = {
    "properties": {
        "linkedServiceName": {
            "referenceName": linked_service_name,
            "type": "LinkedServiceReference"
        },
        "type": "DelimitedText",
        "typeProperties": {
            "location": {
                "type": "AzureBlobFSLocation",
                "folderPath": "output",
                "fileSystem": "processed"
            },
            "columnDelimiter": ","
        },
        "schema": []
    }
}

try:
    # Check if sink dataset exists; if not, create it.
    existing = datafactory_client.datasets.get(RESOURCE_GROUP, ADF_NAME, sink_dataset_name)
    if existing:
        print(f"Sink dataset already present: {sink_dataset_name}")
        created_components.add("Sink Dataset")
except Exception as e:
    # Not found or error checking — attempt to create
    print(f"Sink dataset check error (will attempt create): {e}")
    try:
        result = datafactory_client.datasets.create_or_update(
            RESOURCE_GROUP,
            ADF_NAME,
            sink_dataset_name,
            sink_dataset_payload
        )

        print("Sink dataset created:", getattr(result, 'name', result))
        created_components.add("Sink Dataset")
    except Exception as e:
        print(f"Sink dataset error: {e}")

# ============================================================
# PIPELINE 1 - BAD COSTLY PIPELINE
# ============================================================

print("Creating bad costly pipeline...")

bad_pipeline_name = "PL_Copy_FullLoad_Bad"

bad_pipeline_payload = {
    "properties": {
        "activities": [
            {
                "name": "Wait_30_Sec",
                "type": "Wait",
                "typeProperties": {
                    "waitTimeInSeconds": 30
                }
            },
            {
                "name": "Copy_Full_Load",
                "type": "Copy",
                "dependsOn": [
                    {
                        "activity": "Wait_30_Sec",
                        "dependencyConditions": [
                            "Succeeded"
                        ]
                    }
                ],
                "policy": {
                    "retry": 3,
                    "retryIntervalInSeconds": 20,
                    "timeout": "7.00:00:00"
                },
                "typeProperties": {
                    "source": {
                        "type": "DelimitedTextSource"
                    },
                    "sink": {
                        "type": "DelimitedTextSink"
                    }
                },
                "inputs": [
                    {
                        "referenceName": source_dataset_name,
                        "type": "DatasetReference"
                    }
                ],
                "outputs": [
                    {
                        "referenceName": sink_dataset_name,
                        "type": "DatasetReference"
                    }
                ]
            },
            {
                "name": "Wait_Another_20_Sec",
                "type": "Wait",
                "dependsOn": [
                    {
                        "activity": "Copy_Full_Load",
                        "dependencyConditions": [
                            "Succeeded"
                        ]
                    }
                ],
                "typeProperties": {
                    "waitTimeInSeconds": 20
                }
            }
        ]
    }
}

try:
    # Check if bad pipeline exists; if not, create it.
    existing = datafactory_client.pipelines.get(RESOURCE_GROUP, ADF_NAME, bad_pipeline_name)
    if existing:
        print(f"Bad pipeline already present: {bad_pipeline_name}")
        created_components.add("Bad Costly Pipeline")
except Exception as e:
    # Not found or error checking — attempt to create
    print(f"Bad pipeline check error (will attempt create): {e}")
    try:
        result = datafactory_client.pipelines.create_or_update(
            RESOURCE_GROUP,
            ADF_NAME,
            bad_pipeline_name,
            bad_pipeline_payload
        )

        print("Bad pipeline created:", getattr(result, 'name', result))
        created_components.add("Bad Costly Pipeline")
    except Exception as e:
        print(f"Bad pipeline error: {e}")

# ============================================================
# PIPELINE 2 - OPTIMIZED PIPELINE
# ============================================================

print("Creating optimized pipeline...")

good_pipeline_name = "PL_Copy_Incremental_Good"

good_pipeline_payload = {
    "properties": {
        "activities": [
            {
                "name": "Copy_Incremental_Data",
                "type": "Copy",
                "policy": {
                    "retry": 1,
                    "retryIntervalInSeconds": 5,
                    "timeout": "1.00:00:00"
                },
                "typeProperties": {
                    "source": {
                        "type": "DelimitedTextSource"
                    },
                    "sink": {
                        "type": "DelimitedTextSink"
                    }
                },
                "inputs": [
                    {
                        "referenceName": source_dataset_name,
                        "type": "DatasetReference"
                    }
                ],
                "outputs": [
                    {
                        "referenceName": sink_dataset_name,
                        "type": "DatasetReference"
                    }
                ]
            }
        ]
    }
}

try:
    # Create or update the optimized pipeline. Existing pipelines are updated.
    result = datafactory_client.pipelines.create_or_update(
        RESOURCE_GROUP,
        ADF_NAME,
        good_pipeline_name,
        good_pipeline_payload
    )

    print("Optimized pipeline created:", getattr(result, 'name', result))
    created_components.add("Optimized Pipeline")

except Exception as e:
    print(f"Optimized pipeline error: {e}")
    # Verify existence
    try:
        existing = datafactory_client.pipelines.get(RESOURCE_GROUP, ADF_NAME, good_pipeline_name)
        if existing:
            print(f"Optimized pipeline already present: {good_pipeline_name}")
            created_components.add("Optimized Pipeline")
    except Exception as e:
        print(f"Warning checking optimized pipeline existence: {e}")

# ============================================================
# EXECUTION SUMMARY
# ============================================================

print("\n====================================================")
print("ADF ENVIRONMENT CREATION COMPLETED")
print("====================================================")

print(f"ADF Name: {ADF_NAME}")
print(f"Storage Account: {STORAGE_ACCOUNT_NAME}")
print("\nCreated Components:")
if created_components:
    for comp in sorted(created_components):
        print(f"- {comp}")
else:
    print("- (none)")

print("\nNEXT STEPS")
print("1. Open ADF Studio")
print("2. Validate pipelines")
print("3. Trigger both pipelines multiple times")
print("4. Enable diagnostic settings")
print("5. Connect Log Analytics")
print("6. Build Power BI dashboards")
