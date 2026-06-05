# ============================================================
print(f"Container Exists: {container}")

# ============================================================
# GENERATE LARGE SAMPLE DATA
# ============================================================

print("Generating large dataset...")

# Linked service payload for ADLS Gen2
linked_service_payload = {
    "properties": {
        "type": "AzureBlobFS",
        "typeProperties": {
            "url": f"https://{STORAGE_ACCOUNT_NAME}.dfs.core.windows.net"
        }
    }
}

print("Creating Linked Service...")

datafactory_client.linked_services.create_or_update(
    RESOURCE_GROUP,
    ADF_NAME,
    linked_service_name,
    
                                    "DatasetReference"
                                }
                            ],

                            "outputs": [

                                {
                                    "referenceName":
                                    sink_dataset_name,

                                    "type":
                                    "DatasetReference"
                                }
                            ]
                        },

                        {
                            "name": "Wait_120_Seconds",

                            "type": "Wait",

                            "typeProperties": {

                                "waitTimeInSeconds": 120
                            }
                        }
                    ]
                }
            }
        ]
    }
}

datafactory_client.pipelines.create_or_update(
    RESOURCE_GROUP,
    ADF_NAME,
    pipeline_name,
    pipeline_payload
)

print("High Cost Pipeline Created")

# ============================================================
# COMPLETED
# ============================================================

print("\n================================================")
print("ADF HIGH COST ENVIRONMENT CREATED")
print("================================================")

print(f"ADF NAME: {ADF_NAME}")

print(f"PIPELINE: {pipeline_name}")

print("\nNEXT STEPS")

print("1. Open Azure Data Factory Studio")

print("2. Trigger pipeline multiple times")

print("3. Run 5 to 10 executions")

print("4. Enable Diagnostic Settings")

print("5. Check Azure Cost Management")

print("\nIMPORTANT")

print("COPY ACTIVITY ALONE MAY STILL COST LESS")

print("FOR REAL COST:")

print("- Create Mapping Data Flow")
print("- Use 16 Core General Compute")
print("- TTL = 60 mins")
print("- Enable Debug Session")

print("\nThat generates visible billing quickly.")

print("\nDONE")

# ============================================================
# INSTALL REQUIRED PACKAGES
# ============================================================

#
# pip install azure-identity
# pip install azure-mgmt-datafactory
# pip install azure-storage-file-datalake
# pip install pandas
#
# ============================================================