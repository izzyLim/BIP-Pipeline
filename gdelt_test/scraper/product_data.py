"""
스마트폰 제품 출시 데이터
수동 정리 + 공개 데이터 기반
"""

import pandas as pd
import psycopg2
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 주요 스마트폰 출시 데이터 (2020-2024)
# 출처: 공개 보도자료, Wikipedia 등
PRODUCT_RELEASES = [
    # Samsung - Flagship
    {"brand": "Samsung", "product_name": "Galaxy S20", "segment": "flagship", "release_date": "2020-03-06", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy S20+", "segment": "flagship", "release_date": "2020-03-06", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy S20 Ultra", "segment": "flagship", "release_date": "2020-03-06", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy Note 20", "segment": "flagship", "release_date": "2020-08-21", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy Note 20 Ultra", "segment": "flagship", "release_date": "2020-08-21", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy Z Fold 2", "segment": "flagship", "release_date": "2020-09-18", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy S21", "segment": "flagship", "release_date": "2021-01-29", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy S21+", "segment": "flagship", "release_date": "2021-01-29", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy S21 Ultra", "segment": "flagship", "release_date": "2021-01-29", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy Z Fold 3", "segment": "flagship", "release_date": "2021-08-27", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy Z Flip 3", "segment": "flagship", "release_date": "2021-08-27", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy S22", "segment": "flagship", "release_date": "2022-02-25", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy S22+", "segment": "flagship", "release_date": "2022-02-25", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy S22 Ultra", "segment": "flagship", "release_date": "2022-02-25", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy Z Fold 4", "segment": "flagship", "release_date": "2022-08-26", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy Z Flip 4", "segment": "flagship", "release_date": "2022-08-26", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy S23", "segment": "flagship", "release_date": "2023-02-17", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy S23+", "segment": "flagship", "release_date": "2023-02-17", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy S23 Ultra", "segment": "flagship", "release_date": "2023-02-17", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy Z Fold 5", "segment": "flagship", "release_date": "2023-08-11", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy Z Flip 5", "segment": "flagship", "release_date": "2023-08-11", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy S24", "segment": "flagship", "release_date": "2024-01-31", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy S24+", "segment": "flagship", "release_date": "2024-01-31", "regions": ["North America", "Western Europe", "South Korea"]},
    {"brand": "Samsung", "product_name": "Galaxy S24 Ultra", "segment": "flagship", "release_date": "2024-01-31", "regions": ["North America", "Western Europe", "South Korea"]},

    # Samsung - Mid-range
    {"brand": "Samsung", "product_name": "Galaxy A51", "segment": "mid-range", "release_date": "2020-01-10", "regions": ["North America", "Western Europe", "India", "Southeast Asia"]},
    {"brand": "Samsung", "product_name": "Galaxy A71", "segment": "mid-range", "release_date": "2020-01-17", "regions": ["North America", "Western Europe", "India", "Southeast Asia"]},
    {"brand": "Samsung", "product_name": "Galaxy A52", "segment": "mid-range", "release_date": "2021-03-26", "regions": ["North America", "Western Europe", "India", "Southeast Asia"]},
    {"brand": "Samsung", "product_name": "Galaxy A72", "segment": "mid-range", "release_date": "2021-03-26", "regions": ["North America", "Western Europe", "India", "Southeast Asia"]},
    {"brand": "Samsung", "product_name": "Galaxy A53 5G", "segment": "mid-range", "release_date": "2022-04-01", "regions": ["North America", "Western Europe", "India", "Southeast Asia"]},
    {"brand": "Samsung", "product_name": "Galaxy A54 5G", "segment": "mid-range", "release_date": "2023-04-06", "regions": ["North America", "Western Europe", "India", "Southeast Asia"]},

    # Samsung - Entry
    {"brand": "Samsung", "product_name": "Galaxy A21s", "segment": "entry", "release_date": "2020-06-19", "regions": ["India", "Southeast Asia", "MEA"]},
    {"brand": "Samsung", "product_name": "Galaxy M31", "segment": "entry", "release_date": "2020-03-05", "regions": ["India", "Southeast Asia"]},
    {"brand": "Samsung", "product_name": "Galaxy A32", "segment": "entry", "release_date": "2021-02-25", "regions": ["India", "Southeast Asia", "CALA"]},
    {"brand": "Samsung", "product_name": "Galaxy A13", "segment": "entry", "release_date": "2022-03-23", "regions": ["India", "Southeast Asia", "MEA", "CALA"]},
    {"brand": "Samsung", "product_name": "Galaxy A14", "segment": "entry", "release_date": "2023-01-11", "regions": ["India", "Southeast Asia", "MEA", "CALA"]},

    # Apple - Flagship
    {"brand": "Apple", "product_name": "iPhone 11", "segment": "flagship", "release_date": "2019-09-20", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 11 Pro", "segment": "flagship", "release_date": "2019-09-20", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 11 Pro Max", "segment": "flagship", "release_date": "2019-09-20", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone SE (2020)", "segment": "mid-range", "release_date": "2020-04-24", "regions": ["North America", "Western Europe", "China", "Japan", "India"]},
    {"brand": "Apple", "product_name": "iPhone 12", "segment": "flagship", "release_date": "2020-10-23", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 12 Mini", "segment": "flagship", "release_date": "2020-11-13", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 12 Pro", "segment": "flagship", "release_date": "2020-10-23", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 12 Pro Max", "segment": "flagship", "release_date": "2020-11-13", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 13", "segment": "flagship", "release_date": "2021-09-24", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 13 Mini", "segment": "flagship", "release_date": "2021-09-24", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 13 Pro", "segment": "flagship", "release_date": "2021-09-24", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 13 Pro Max", "segment": "flagship", "release_date": "2021-09-24", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone SE (2022)", "segment": "mid-range", "release_date": "2022-03-18", "regions": ["North America", "Western Europe", "China", "Japan", "India"]},
    {"brand": "Apple", "product_name": "iPhone 14", "segment": "flagship", "release_date": "2022-09-16", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 14 Plus", "segment": "flagship", "release_date": "2022-10-07", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 14 Pro", "segment": "flagship", "release_date": "2022-09-16", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 14 Pro Max", "segment": "flagship", "release_date": "2022-09-16", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 15", "segment": "flagship", "release_date": "2023-09-22", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 15 Plus", "segment": "flagship", "release_date": "2023-09-22", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 15 Pro", "segment": "flagship", "release_date": "2023-09-22", "regions": ["North America", "Western Europe", "China", "Japan"]},
    {"brand": "Apple", "product_name": "iPhone 15 Pro Max", "segment": "flagship", "release_date": "2023-09-22", "regions": ["North America", "Western Europe", "China", "Japan"]},

    # Xiaomi
    {"brand": "Xiaomi", "product_name": "Mi 10", "segment": "flagship", "release_date": "2020-02-14", "regions": ["China", "Western Europe", "India"]},
    {"brand": "Xiaomi", "product_name": "Mi 10 Pro", "segment": "flagship", "release_date": "2020-02-14", "regions": ["China", "Western Europe", "India"]},
    {"brand": "Xiaomi", "product_name": "Mi 11", "segment": "flagship", "release_date": "2021-01-01", "regions": ["China", "Western Europe", "India"]},
    {"brand": "Xiaomi", "product_name": "Mi 11 Ultra", "segment": "flagship", "release_date": "2021-04-23", "regions": ["China", "Western Europe", "India"]},
    {"brand": "Xiaomi", "product_name": "Xiaomi 12", "segment": "flagship", "release_date": "2022-03-15", "regions": ["China", "Western Europe", "India"]},
    {"brand": "Xiaomi", "product_name": "Xiaomi 13", "segment": "flagship", "release_date": "2023-03-08", "regions": ["China", "Western Europe", "India"]},
    {"brand": "Xiaomi", "product_name": "Xiaomi 14", "segment": "flagship", "release_date": "2024-02-25", "regions": ["China", "Western Europe", "India"]},
    {"brand": "Xiaomi", "product_name": "Redmi Note 9", "segment": "mid-range", "release_date": "2020-06-04", "regions": ["China", "India", "Southeast Asia"]},
    {"brand": "Xiaomi", "product_name": "Redmi Note 10", "segment": "mid-range", "release_date": "2021-03-04", "regions": ["China", "India", "Southeast Asia"]},
    {"brand": "Xiaomi", "product_name": "Redmi Note 11", "segment": "mid-range", "release_date": "2022-01-26", "regions": ["China", "India", "Southeast Asia"]},
    {"brand": "Xiaomi", "product_name": "Redmi Note 12", "segment": "mid-range", "release_date": "2023-01-05", "regions": ["China", "India", "Southeast Asia"]},
    {"brand": "Xiaomi", "product_name": "Redmi 9", "segment": "entry", "release_date": "2020-06-10", "regions": ["China", "India", "Southeast Asia"]},
    {"brand": "Xiaomi", "product_name": "Redmi 10", "segment": "entry", "release_date": "2021-08-18", "regions": ["China", "India", "Southeast Asia"]},

    # Huawei
    {"brand": "Huawei", "product_name": "P40", "segment": "flagship", "release_date": "2020-04-07", "regions": ["China", "Western Europe", "MEA"]},
    {"brand": "Huawei", "product_name": "P40 Pro", "segment": "flagship", "release_date": "2020-04-07", "regions": ["China", "Western Europe", "MEA"]},
    {"brand": "Huawei", "product_name": "Mate 40 Pro", "segment": "flagship", "release_date": "2020-10-30", "regions": ["China", "Western Europe", "MEA"]},
    {"brand": "Huawei", "product_name": "P50 Pro", "segment": "flagship", "release_date": "2021-07-29", "regions": ["China"]},
    {"brand": "Huawei", "product_name": "Mate 50 Pro", "segment": "flagship", "release_date": "2022-09-21", "regions": ["China"]},
    {"brand": "Huawei", "product_name": "Mate 60 Pro", "segment": "flagship", "release_date": "2023-09-08", "regions": ["China"]},

    # OPPO
    {"brand": "OPPO", "product_name": "Find X2 Pro", "segment": "flagship", "release_date": "2020-03-06", "regions": ["China", "Western Europe", "India"]},
    {"brand": "OPPO", "product_name": "Find X3 Pro", "segment": "flagship", "release_date": "2021-03-11", "regions": ["China", "Western Europe", "India"]},
    {"brand": "OPPO", "product_name": "Find X5 Pro", "segment": "flagship", "release_date": "2022-03-01", "regions": ["China", "Western Europe", "India"]},
    {"brand": "OPPO", "product_name": "Reno 4", "segment": "mid-range", "release_date": "2020-06-05", "regions": ["China", "India", "Southeast Asia"]},
    {"brand": "OPPO", "product_name": "Reno 5", "segment": "mid-range", "release_date": "2020-12-10", "regions": ["China", "India", "Southeast Asia"]},
    {"brand": "OPPO", "product_name": "Reno 6", "segment": "mid-range", "release_date": "2021-05-27", "regions": ["China", "India", "Southeast Asia"]},
    {"brand": "OPPO", "product_name": "A54", "segment": "entry", "release_date": "2021-04-02", "regions": ["India", "Southeast Asia", "MEA"]},

    # Google
    {"brand": "Google", "product_name": "Pixel 4a", "segment": "mid-range", "release_date": "2020-08-20", "regions": ["North America", "Japan"]},
    {"brand": "Google", "product_name": "Pixel 5", "segment": "flagship", "release_date": "2020-10-15", "regions": ["North America", "Japan", "Western Europe"]},
    {"brand": "Google", "product_name": "Pixel 6", "segment": "flagship", "release_date": "2021-10-28", "regions": ["North America", "Japan", "Western Europe"]},
    {"brand": "Google", "product_name": "Pixel 6 Pro", "segment": "flagship", "release_date": "2021-10-28", "regions": ["North America", "Japan", "Western Europe"]},
    {"brand": "Google", "product_name": "Pixel 6a", "segment": "mid-range", "release_date": "2022-07-28", "regions": ["North America", "Japan", "Western Europe"]},
    {"brand": "Google", "product_name": "Pixel 7", "segment": "flagship", "release_date": "2022-10-13", "regions": ["North America", "Japan", "Western Europe"]},
    {"brand": "Google", "product_name": "Pixel 7 Pro", "segment": "flagship", "release_date": "2022-10-13", "regions": ["North America", "Japan", "Western Europe"]},
    {"brand": "Google", "product_name": "Pixel 7a", "segment": "mid-range", "release_date": "2023-05-11", "regions": ["North America", "Japan", "Western Europe"]},
    {"brand": "Google", "product_name": "Pixel 8", "segment": "flagship", "release_date": "2023-10-12", "regions": ["North America", "Japan", "Western Europe"]},
    {"brand": "Google", "product_name": "Pixel 8 Pro", "segment": "flagship", "release_date": "2023-10-12", "regions": ["North America", "Japan", "Western Europe"]},
    {"brand": "Google", "product_name": "Pixel 8a", "segment": "mid-range", "release_date": "2024-05-14", "regions": ["North America", "Japan", "Western Europe"]},

    # OnePlus
    {"brand": "OnePlus", "product_name": "OnePlus 8", "segment": "flagship", "release_date": "2020-04-21", "regions": ["North America", "Western Europe", "India"]},
    {"brand": "OnePlus", "product_name": "OnePlus 8 Pro", "segment": "flagship", "release_date": "2020-04-21", "regions": ["North America", "Western Europe", "India"]},
    {"brand": "OnePlus", "product_name": "OnePlus 8T", "segment": "flagship", "release_date": "2020-10-16", "regions": ["North America", "Western Europe", "India"]},
    {"brand": "OnePlus", "product_name": "OnePlus Nord", "segment": "mid-range", "release_date": "2020-08-04", "regions": ["Western Europe", "India"]},
    {"brand": "OnePlus", "product_name": "OnePlus 9", "segment": "flagship", "release_date": "2021-03-26", "regions": ["North America", "Western Europe", "India"]},
    {"brand": "OnePlus", "product_name": "OnePlus 9 Pro", "segment": "flagship", "release_date": "2021-03-26", "regions": ["North America", "Western Europe", "India"]},
    {"brand": "OnePlus", "product_name": "OnePlus Nord 2", "segment": "mid-range", "release_date": "2021-07-28", "regions": ["Western Europe", "India"]},
    {"brand": "OnePlus", "product_name": "OnePlus 10 Pro", "segment": "flagship", "release_date": "2022-04-05", "regions": ["North America", "Western Europe", "India"]},
    {"brand": "OnePlus", "product_name": "OnePlus 10T", "segment": "flagship", "release_date": "2022-08-06", "regions": ["North America", "Western Europe", "India"]},
    {"brand": "OnePlus", "product_name": "OnePlus Nord CE 2", "segment": "mid-range", "release_date": "2022-02-17", "regions": ["Western Europe", "India"]},
    {"brand": "OnePlus", "product_name": "OnePlus 11", "segment": "flagship", "release_date": "2023-02-16", "regions": ["North America", "Western Europe", "India", "China"]},
    {"brand": "OnePlus", "product_name": "OnePlus Nord 3", "segment": "mid-range", "release_date": "2023-07-05", "regions": ["Western Europe", "India"]},
    {"brand": "OnePlus", "product_name": "OnePlus 12", "segment": "flagship", "release_date": "2024-01-23", "regions": ["North America", "Western Europe", "India", "China"]},
    {"brand": "OnePlus", "product_name": "OnePlus 12R", "segment": "mid-range", "release_date": "2024-02-06", "regions": ["North America", "India"]},

    # Vivo
    {"brand": "Vivo", "product_name": "Vivo X50 Pro", "segment": "flagship", "release_date": "2020-07-16", "regions": ["China", "India", "Southeast Asia"]},
    {"brand": "Vivo", "product_name": "Vivo X60 Pro", "segment": "flagship", "release_date": "2021-01-08", "regions": ["China", "India", "Southeast Asia"]},
    {"brand": "Vivo", "product_name": "Vivo X70 Pro", "segment": "flagship", "release_date": "2021-09-10", "regions": ["China", "India", "Southeast Asia"]},
    {"brand": "Vivo", "product_name": "Vivo X80 Pro", "segment": "flagship", "release_date": "2022-05-10", "regions": ["China", "India", "Southeast Asia"]},
    {"brand": "Vivo", "product_name": "Vivo X90 Pro", "segment": "flagship", "release_date": "2023-01-04", "regions": ["China", "India", "Southeast Asia"]},
    {"brand": "Vivo", "product_name": "Vivo X100 Pro", "segment": "flagship", "release_date": "2024-01-08", "regions": ["China", "India", "Southeast Asia"]},
    {"brand": "Vivo", "product_name": "Vivo V20", "segment": "mid-range", "release_date": "2020-10-13", "regions": ["India", "Southeast Asia"]},
    {"brand": "Vivo", "product_name": "Vivo V21", "segment": "mid-range", "release_date": "2021-04-29", "regions": ["India", "Southeast Asia"]},
    {"brand": "Vivo", "product_name": "Vivo V23", "segment": "mid-range", "release_date": "2022-01-05", "regions": ["India", "Southeast Asia"]},
    {"brand": "Vivo", "product_name": "Vivo V25", "segment": "mid-range", "release_date": "2022-08-25", "regions": ["India", "Southeast Asia"]},
    {"brand": "Vivo", "product_name": "Vivo V27", "segment": "mid-range", "release_date": "2023-03-01", "regions": ["India", "Southeast Asia"]},
    {"brand": "Vivo", "product_name": "Vivo Y20", "segment": "entry", "release_date": "2020-08-28", "regions": ["India", "Southeast Asia", "MEA"]},
    {"brand": "Vivo", "product_name": "Vivo Y21", "segment": "entry", "release_date": "2021-08-23", "regions": ["India", "Southeast Asia", "MEA"]},
    {"brand": "Vivo", "product_name": "Vivo Y22", "segment": "entry", "release_date": "2022-09-12", "regions": ["India", "Southeast Asia", "MEA"]},
    {"brand": "Vivo", "product_name": "Vivo Y35", "segment": "entry", "release_date": "2022-08-05", "regions": ["India", "Southeast Asia", "MEA"]},

    # Realme
    {"brand": "Realme", "product_name": "Realme 6 Pro", "segment": "mid-range", "release_date": "2020-03-05", "regions": ["India", "Southeast Asia"]},
    {"brand": "Realme", "product_name": "Realme 7 Pro", "segment": "mid-range", "release_date": "2020-09-03", "regions": ["India", "Southeast Asia"]},
    {"brand": "Realme", "product_name": "Realme X50 Pro", "segment": "flagship", "release_date": "2020-02-24", "regions": ["China", "India"]},
    {"brand": "Realme", "product_name": "Realme GT", "segment": "flagship", "release_date": "2021-03-04", "regions": ["China", "India", "Western Europe"]},
    {"brand": "Realme", "product_name": "Realme GT 2 Pro", "segment": "flagship", "release_date": "2022-01-04", "regions": ["China", "India", "Western Europe"]},
    {"brand": "Realme", "product_name": "Realme GT 3", "segment": "flagship", "release_date": "2023-02-28", "regions": ["China", "India", "Western Europe"]},
    {"brand": "Realme", "product_name": "Realme 8 Pro", "segment": "mid-range", "release_date": "2021-03-24", "regions": ["India", "Southeast Asia"]},
    {"brand": "Realme", "product_name": "Realme 9 Pro+", "segment": "mid-range", "release_date": "2022-02-16", "regions": ["India", "Southeast Asia"]},
    {"brand": "Realme", "product_name": "Realme 10 Pro+", "segment": "mid-range", "release_date": "2022-12-08", "regions": ["India", "Southeast Asia"]},
    {"brand": "Realme", "product_name": "Realme 11 Pro+", "segment": "mid-range", "release_date": "2023-06-08", "regions": ["India", "Southeast Asia"]},
    {"brand": "Realme", "product_name": "Realme C11", "segment": "entry", "release_date": "2020-06-30", "regions": ["India", "Southeast Asia", "MEA"]},
    {"brand": "Realme", "product_name": "Realme C21", "segment": "entry", "release_date": "2021-03-05", "regions": ["India", "Southeast Asia", "MEA"]},
    {"brand": "Realme", "product_name": "Realme C31", "segment": "entry", "release_date": "2022-03-06", "regions": ["India", "Southeast Asia", "MEA"]},
    {"brand": "Realme", "product_name": "Realme C55", "segment": "entry", "release_date": "2023-03-07", "regions": ["India", "Southeast Asia", "MEA"]},

    # Motorola
    {"brand": "Motorola", "product_name": "Moto G Power (2020)", "segment": "entry", "release_date": "2020-04-16", "regions": ["North America", "CALA"]},
    {"brand": "Motorola", "product_name": "Moto G Stylus (2020)", "segment": "mid-range", "release_date": "2020-04-16", "regions": ["North America"]},
    {"brand": "Motorola", "product_name": "Motorola Edge", "segment": "flagship", "release_date": "2020-05-14", "regions": ["North America", "Western Europe"]},
    {"brand": "Motorola", "product_name": "Motorola Edge+", "segment": "flagship", "release_date": "2020-05-14", "regions": ["North America"]},
    {"brand": "Motorola", "product_name": "Moto G Power (2021)", "segment": "entry", "release_date": "2021-01-14", "regions": ["North America", "CALA"]},
    {"brand": "Motorola", "product_name": "Motorola Edge 20 Pro", "segment": "flagship", "release_date": "2021-08-05", "regions": ["North America", "Western Europe"]},
    {"brand": "Motorola", "product_name": "Moto G Power (2022)", "segment": "entry", "release_date": "2022-03-01", "regions": ["North America", "CALA"]},
    {"brand": "Motorola", "product_name": "Motorola Edge 30 Pro", "segment": "flagship", "release_date": "2022-02-24", "regions": ["North America", "Western Europe"]},
    {"brand": "Motorola", "product_name": "Motorola Razr (2022)", "segment": "flagship", "release_date": "2022-08-11", "regions": ["North America", "Western Europe", "China"]},
    {"brand": "Motorola", "product_name": "Motorola Edge 40 Pro", "segment": "flagship", "release_date": "2023-04-13", "regions": ["North America", "Western Europe"]},
    {"brand": "Motorola", "product_name": "Motorola Razr 40 Ultra", "segment": "flagship", "release_date": "2023-06-01", "regions": ["North America", "Western Europe", "China"]},
    {"brand": "Motorola", "product_name": "Moto G Power 5G (2024)", "segment": "mid-range", "release_date": "2024-02-22", "regions": ["North America"]},

    # Sony
    {"brand": "Sony", "product_name": "Sony Xperia 1 II", "segment": "flagship", "release_date": "2020-06-04", "regions": ["North America", "Western Europe", "Japan"]},
    {"brand": "Sony", "product_name": "Sony Xperia 5 II", "segment": "flagship", "release_date": "2020-10-30", "regions": ["North America", "Western Europe", "Japan"]},
    {"brand": "Sony", "product_name": "Sony Xperia 1 III", "segment": "flagship", "release_date": "2021-07-09", "regions": ["North America", "Western Europe", "Japan"]},
    {"brand": "Sony", "product_name": "Sony Xperia 5 III", "segment": "flagship", "release_date": "2021-10-29", "regions": ["North America", "Western Europe", "Japan"]},
    {"brand": "Sony", "product_name": "Sony Xperia 1 IV", "segment": "flagship", "release_date": "2022-06-03", "regions": ["North America", "Western Europe", "Japan"]},
    {"brand": "Sony", "product_name": "Sony Xperia 5 IV", "segment": "flagship", "release_date": "2022-10-27", "regions": ["North America", "Western Europe", "Japan"]},
    {"brand": "Sony", "product_name": "Sony Xperia 1 V", "segment": "flagship", "release_date": "2023-07-20", "regions": ["North America", "Western Europe", "Japan"]},
    {"brand": "Sony", "product_name": "Sony Xperia 10 IV", "segment": "mid-range", "release_date": "2022-06-09", "regions": ["Western Europe", "Japan"]},
    {"brand": "Sony", "product_name": "Sony Xperia 10 V", "segment": "mid-range", "release_date": "2023-07-20", "regions": ["Western Europe", "Japan"]},

    # Nothing
    {"brand": "Nothing", "product_name": "Nothing Phone (1)", "segment": "mid-range", "release_date": "2022-07-21", "regions": ["Western Europe", "India", "Japan"]},
    {"brand": "Nothing", "product_name": "Nothing Phone (2)", "segment": "mid-range", "release_date": "2023-07-11", "regions": ["North America", "Western Europe", "India", "Japan"]},
    {"brand": "Nothing", "product_name": "Nothing Phone (2a)", "segment": "mid-range", "release_date": "2024-03-05", "regions": ["Western Europe", "India"]},

    # Tecno (Africa/MEA focused)
    {"brand": "Tecno", "product_name": "Tecno Camon 15", "segment": "entry", "release_date": "2020-04-03", "regions": ["MEA", "India"]},
    {"brand": "Tecno", "product_name": "Tecno Camon 16", "segment": "entry", "release_date": "2020-09-03", "regions": ["MEA", "India"]},
    {"brand": "Tecno", "product_name": "Tecno Camon 17", "segment": "entry", "release_date": "2021-06-14", "regions": ["MEA", "India"]},
    {"brand": "Tecno", "product_name": "Tecno Camon 18", "segment": "entry", "release_date": "2021-10-07", "regions": ["MEA", "India"]},
    {"brand": "Tecno", "product_name": "Tecno Camon 19 Pro", "segment": "mid-range", "release_date": "2022-06-14", "regions": ["MEA", "India"]},
    {"brand": "Tecno", "product_name": "Tecno Camon 20 Pro", "segment": "mid-range", "release_date": "2023-05-10", "regions": ["MEA", "India"]},
    {"brand": "Tecno", "product_name": "Tecno Spark 6", "segment": "entry", "release_date": "2020-09-15", "regions": ["MEA", "India", "Southeast Asia"]},
    {"brand": "Tecno", "product_name": "Tecno Spark 7", "segment": "entry", "release_date": "2021-03-25", "regions": ["MEA", "India", "Southeast Asia"]},
    {"brand": "Tecno", "product_name": "Tecno Spark 8", "segment": "entry", "release_date": "2021-09-13", "regions": ["MEA", "India", "Southeast Asia"]},
    {"brand": "Tecno", "product_name": "Tecno Spark 10 Pro", "segment": "entry", "release_date": "2023-02-25", "regions": ["MEA", "India", "Southeast Asia"]},

    # Infinix (Africa/MEA focused)
    {"brand": "Infinix", "product_name": "Infinix Note 7", "segment": "entry", "release_date": "2020-06-05", "regions": ["MEA", "India"]},
    {"brand": "Infinix", "product_name": "Infinix Note 8", "segment": "entry", "release_date": "2020-09-09", "regions": ["MEA", "India"]},
    {"brand": "Infinix", "product_name": "Infinix Note 10 Pro", "segment": "mid-range", "release_date": "2021-06-08", "regions": ["MEA", "India"]},
    {"brand": "Infinix", "product_name": "Infinix Note 11 Pro", "segment": "mid-range", "release_date": "2021-10-13", "regions": ["MEA", "India"]},
    {"brand": "Infinix", "product_name": "Infinix Note 12 Pro", "segment": "mid-range", "release_date": "2022-05-20", "regions": ["MEA", "India"]},
    {"brand": "Infinix", "product_name": "Infinix Zero 20", "segment": "mid-range", "release_date": "2022-10-06", "regions": ["MEA", "India"]},
    {"brand": "Infinix", "product_name": "Infinix Zero 30", "segment": "mid-range", "release_date": "2023-09-15", "regions": ["MEA", "India"]},
    {"brand": "Infinix", "product_name": "Infinix Hot 10", "segment": "entry", "release_date": "2020-10-08", "regions": ["MEA", "India", "Southeast Asia"]},
    {"brand": "Infinix", "product_name": "Infinix Hot 11", "segment": "entry", "release_date": "2021-09-14", "regions": ["MEA", "India", "Southeast Asia"]},
    {"brand": "Infinix", "product_name": "Infinix Hot 12", "segment": "entry", "release_date": "2022-05-17", "regions": ["MEA", "India", "Southeast Asia"]},

    # Itel (Africa/MEA entry-level)
    {"brand": "Itel", "product_name": "Itel A56", "segment": "entry", "release_date": "2020-01-15", "regions": ["MEA"]},
    {"brand": "Itel", "product_name": "Itel Vision 1 Pro", "segment": "entry", "release_date": "2020-09-01", "regions": ["MEA", "India"]},
    {"brand": "Itel", "product_name": "Itel A58", "segment": "entry", "release_date": "2021-07-20", "regions": ["MEA", "India"]},
    {"brand": "Itel", "product_name": "Itel S18", "segment": "entry", "release_date": "2022-09-15", "regions": ["MEA"]},
    {"brand": "Itel", "product_name": "Itel A60", "segment": "entry", "release_date": "2023-03-10", "regions": ["MEA", "India"]},

    # Honor (post-Huawei)
    {"brand": "Honor", "product_name": "Honor 30 Pro", "segment": "flagship", "release_date": "2020-04-15", "regions": ["China"]},
    {"brand": "Honor", "product_name": "Honor 50", "segment": "mid-range", "release_date": "2021-06-16", "regions": ["China", "Western Europe"]},
    {"brand": "Honor", "product_name": "Honor Magic 3 Pro", "segment": "flagship", "release_date": "2021-08-12", "regions": ["China", "Western Europe"]},
    {"brand": "Honor", "product_name": "Honor 70", "segment": "mid-range", "release_date": "2022-05-30", "regions": ["China", "Western Europe"]},
    {"brand": "Honor", "product_name": "Honor Magic 4 Pro", "segment": "flagship", "release_date": "2022-02-28", "regions": ["China", "Western Europe"]},
    {"brand": "Honor", "product_name": "Honor 80 Pro", "segment": "mid-range", "release_date": "2022-11-23", "regions": ["China"]},
    {"brand": "Honor", "product_name": "Honor Magic 5 Pro", "segment": "flagship", "release_date": "2023-03-06", "regions": ["China", "Western Europe"]},
    {"brand": "Honor", "product_name": "Honor 90", "segment": "mid-range", "release_date": "2023-05-29", "regions": ["China", "Western Europe"]},
    {"brand": "Honor", "product_name": "Honor Magic 6 Pro", "segment": "flagship", "release_date": "2024-01-11", "regions": ["China", "Western Europe"]},

    # ZTE/Nubia
    {"brand": "ZTE", "product_name": "ZTE Axon 20", "segment": "mid-range", "release_date": "2020-09-01", "regions": ["China", "Western Europe"]},
    {"brand": "ZTE", "product_name": "ZTE Axon 30 Ultra", "segment": "flagship", "release_date": "2021-04-15", "regions": ["China", "Western Europe"]},
    {"brand": "ZTE", "product_name": "ZTE Axon 40 Ultra", "segment": "flagship", "release_date": "2022-05-09", "regions": ["China", "Western Europe"]},
    {"brand": "Nubia", "product_name": "Nubia Red Magic 5G", "segment": "flagship", "release_date": "2020-03-12", "regions": ["China", "North America", "Western Europe"]},
    {"brand": "Nubia", "product_name": "Nubia Red Magic 6", "segment": "flagship", "release_date": "2021-03-04", "regions": ["China", "North America", "Western Europe"]},
    {"brand": "Nubia", "product_name": "Nubia Red Magic 7", "segment": "flagship", "release_date": "2022-02-17", "regions": ["China", "North America", "Western Europe"]},
    {"brand": "Nubia", "product_name": "Nubia Red Magic 8 Pro", "segment": "flagship", "release_date": "2022-12-26", "regions": ["China", "North America", "Western Europe"]},

    # ASUS ROG (Gaming)
    {"brand": "ASUS", "product_name": "ASUS ROG Phone 3", "segment": "flagship", "release_date": "2020-07-22", "regions": ["North America", "Western Europe", "India"]},
    {"brand": "ASUS", "product_name": "ASUS ROG Phone 5", "segment": "flagship", "release_date": "2021-03-10", "regions": ["North America", "Western Europe", "India"]},
    {"brand": "ASUS", "product_name": "ASUS ROG Phone 6", "segment": "flagship", "release_date": "2022-07-05", "regions": ["North America", "Western Europe", "India"]},
    {"brand": "ASUS", "product_name": "ASUS ROG Phone 7", "segment": "flagship", "release_date": "2023-04-13", "regions": ["North America", "Western Europe", "India"]},
    {"brand": "ASUS", "product_name": "ASUS Zenfone 8", "segment": "flagship", "release_date": "2021-05-12", "regions": ["North America", "Western Europe", "Japan"]},
    {"brand": "ASUS", "product_name": "ASUS Zenfone 9", "segment": "flagship", "release_date": "2022-07-28", "regions": ["North America", "Western Europe", "Japan"]},
    {"brand": "ASUS", "product_name": "ASUS Zenfone 10", "segment": "flagship", "release_date": "2023-06-29", "regions": ["North America", "Western Europe", "Japan"]},
]


def get_connection():
    DB_CONFIG = {
        "host": "localhost",
        "port": 5432,
        "user": "user",
        "password": "pw1234",
        "dbname": "stockdb"
    }
    return psycopg2.connect(**DB_CONFIG)


def load_to_db():
    """제품 데이터를 DB에 적재"""
    conn = get_connection()
    cur = conn.cursor()

    inserted = 0
    for product in PRODUCT_RELEASES:
        try:
            regions = product.get('regions', [])

            cur.execute("""
                INSERT INTO product_release (brand, product_name, segment, release_date, regions)
                VALUES (%s, %s, %s::segment_type, %s, %s::region_type[])
                ON CONFLICT (brand, product_name) DO UPDATE
                SET segment = EXCLUDED.segment,
                    release_date = EXCLUDED.release_date,
                    regions = EXCLUDED.regions
            """, (
                product['brand'],
                product['product_name'],
                product['segment'],
                product['release_date'],
                regions
            ))
            inserted += 1
            conn.commit()
        except Exception as e:
            logger.warning(f"Error inserting {product['product_name']}: {e}")
            conn.rollback()

    conn.close()
    logger.info(f"Inserted {inserted} products")
    return inserted


def check_stats():
    """통계 확인"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM product_release")
    total = cur.fetchone()[0]

    cur.execute("""
        SELECT brand, segment, COUNT(*)
        FROM product_release
        GROUP BY brand, segment
        ORDER BY brand, segment
    """)
    by_brand_segment = cur.fetchall()

    cur.execute("""
        SELECT EXTRACT(YEAR FROM release_date) as year, COUNT(*)
        FROM product_release
        GROUP BY year
        ORDER BY year
    """)
    by_year = cur.fetchall()

    conn.close()

    print(f"\n=== Product Release Stats ===")
    print(f"Total: {total}")
    print(f"\nBy Brand & Segment:")
    for brand, segment, count in by_brand_segment:
        print(f"  {brand} - {segment}: {count}")
    print(f"\nBy Year:")
    for year, count in by_year:
        print(f"  {int(year)}: {count}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        check_stats()
    else:
        load_to_db()
        check_stats()
