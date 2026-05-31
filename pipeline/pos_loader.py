import pandas as pd
import requests
from datetime import datetime, timezone


def load_pos_to_api(csv_path: str, api_base_url: str, store_id: str = "ST1008"):
    """
    Reads the actual Purplle POS CSV and POSTs transactions to API.
    Groups item-level rows by invoice_number to get basket totals.
    """

    df = pd.read_csv(csv_path)
    # Group by invoice to get one row per transaction
    invoices = (
        df.groupby(["invoice_number", "order_date", "order_time"])
        .agg(basket_value_inr=("total_amount", "sum"))
        .reset_index()
    )

    transactions = []
    for _, row in invoices.iterrows():
        ts = datetime.strptime(
            f"{row['order_date']} {row['order_time']}",
            "%d-%m-%Y %H:%M:%S"
        ).replace(tzinfo=timezone.utc)

        transactions.append({
            "transaction_id":  row["invoice_number"],
            "store_id":        store_id,
            "timestamp":       ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "basket_value_inr": round(float(row["basket_value_inr"]), 2),
        })

    print(f"Loading {len(transactions)} transactions to API...")

    try:
        resp = requests.post(
            f"{api_base_url}/pos/load",
            json={"transactions": transactions},
            timeout=15
        )
        print(f"Response: {resp.status_code} — {resp.json()}")
    except Exception as e:
        print(f"API unreachable: {e}. Saving to local file instead.")
        import json
        with open("data/pos_transactions_loaded.json", "w") as f:
            json.dump(transactions, f, indent=2)
        print("Saved to data/pos_transactions_loaded.json")

    return transactions


if __name__ == "__main__":
    import sys
    csv = sys.argv[1] if len(sys.argv) > 1 else "data/Brigade_Bangalore_10_April_26.csv"
    load_pos_to_api(csv, "http://localhost:8000")