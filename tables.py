import pandas as pd
import sys
import os
import re

def safe_filename(name: str) -> str:
    """Return a filesystem-safe version of a filename."""
    return re.sub(r'[^A-Za-z0-9_.-]', '_', name)

def csv_to_tsv_files(csv_file):
    df = pd.read_csv(csv_file)
    df["Requests"] = df["Requests"].astype(int)
    df["Users"] = df["Users"].astype(int)

    metrics = [c for c in df.columns if c not in ["Architecture", "Requests", "Users"]]

    base_dir = os.path.splitext(csv_file)[0] + "_tables"
    os.makedirs(base_dir, exist_ok=True)

    for arch, arch_df in df.groupby("Architecture"):
        arch_dir = os.path.join(base_dir, safe_filename(arch))
        os.makedirs(arch_dir, exist_ok=True)

        for metric in metrics:
            pivot = (
                arch_df.pivot_table(
                    index="Requests",
                    columns="Users",
                    values=metric,
                    aggfunc="first"
                )
                .sort_index(axis=0)
                .sort_index(axis=1)
            )

            safe_metric_name = safe_filename(metric)
            tsv_path = os.path.join(arch_dir, f"{safe_metric_name}.tsv")

            pivot.to_csv(tsv_path, sep="\t", float_format="%.3f")
            print(f"✅ Saved {tsv_path}")

    print(f"\nAll tables saved in: {base_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tables.py <csv_file>")
        sys.exit(1)

    csv_to_tsv_files(sys.argv[1])
