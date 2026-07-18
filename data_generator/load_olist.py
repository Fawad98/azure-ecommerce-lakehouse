# Necessary packages
import pandas as pd
from sqlalchemy import create_engine
import urllib
import os

SERVER = "sql-ecomlake-dev.database.windows.net"
DB = "olist"
USER = "lakeadmin"
PWD = os.environ["SQL_PWD"]


params = urllib.parse.quote_plus(
    f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SERVER};"
    f"DATABASE={DB};UID={USER};PWD={PWD};Encrypt=yes;"
)
engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}")

tables = {
    "olist_orders_dataset.csv": "orders",
    "olist_order_items_dataset.csv": "order_items",
    "olist_customers_dataset.csv": "customers",
    "olist_products_dataset.csv": "products",
    "olist_order_payments_dataset.csv": "payments",
    "olist_sellers_dataset.csv": "sellers",
    "olist_order_reviews_dataset.csv": "order_reviews",
    "olist_geolocation_dataset.csv": "geolocation"
}

for csv, table in tables.items():
    df = pd.read_csv(f"./olist/{csv}")
    df.to_sql(table, engine, if_exists="replace", index=False, chunksize=5000)
    print(f"Loaded {table}: {len(df)} rows")