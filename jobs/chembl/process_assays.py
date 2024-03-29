import argparse
import logging
from pathlib import Path

import pyspark.sql.functions as F
import pyspark.sql.types as T
from pyspark.sql import SparkSession

from tpp.preprocessing.chembl.activity_labels import (
    clean_activity_labels,
    generate_activity_labels,
)
from tpp.utils.argcheck import check_input_path, check_output_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="ChEMBL Assay Processing",
        description="Process ChEMBL SQLite dump assay data",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        metavar="PATH",
        dest="input_path",
        help=f"Path to folder with ChEMBL Database in `parquet` format)",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        metavar="PATH",
        dest="output_path",
        help="Path where processed assays should be written to in `parquet` format",
    )
    parser.add_argument(
        "--num-partitions", type=int, dest="num_partitions", default=100
    )

    args = parser.parse_args()

    check_input_path(args.input_path)
    check_output_path(args.output_path)

    generate_activity_labels = F.udf(generate_activity_labels, T.IntegerType())
    clean_activity_labels = F.pandas_udf(
        clean_activity_labels, T.IntegerType(), F.PandasUDFType.GROUPED_AGG
    )

    try:
        spark = (
            SparkSession.builder.appName(parser.prog)
            .config("spark.sql.execution.arrow.enabled", "true")
            .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
            .getOrCreate()
        )

        df = spark.read.parquet(args.input_path.as_posix()).repartition(
            args.num_partitions
        )

        df_processed = df.withColumn(
            "activity",
            generate_activity_labels(
                F.col("activity_comment"),
                F.col("standard_value"),
                F.col("standard_units"),
                F.col("standard_relation"),
            ),
        )

        df_cleaned = df_processed.groupby(["assay_id", "mol_id"]).agg(
            clean_activity_labels(F.col("activity")).alias("activity")
        )

        df_cleaned.write.parquet(args.output_path.as_posix())
    except Exception as e:
        logging.exception(e)
        raise SystemExit(
            "Spark Job encountered a problem. Check the logs for more information"
        )
    finally:
        spark.stop()
