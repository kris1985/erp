"""销售订单 Excel 导入解析测试。"""

from datetime import date
from pathlib import Path

from app.services.sales_order_import import (
    build_sales_order_import_template_bytes,
    parse_sales_order_workbook,
)


def test_parse_packaged_customer_template():
    path = Path(__file__).resolve().parents[1] / "assets" / "templates" / "sales_order_import.xlsx"
    assert path.is_file()
    sheets = parse_sales_order_workbook(path.read_bytes())
    assert len(sheets) == 1
    so = sheets[0]
    assert so["order_no"] == "0000725"
    assert so["customer_name"] == "红丫丫鞋业"
    assert so["ordered_at"] == date(2021, 7, 21)
    assert so["delivery_date"] == date(2021, 8, 23)
    assert so["notes"] and "LOGO" in so["notes"]
    assert len(so["lines"]) == 4
    assert so["lines"][0]["product_code"] == "21L533-25"
    assert so["lines"][0]["color_name"] == "克色"
    assert so["lines"][0]["fabric"] == "开边珠"
    assert so["lines"][0]["lining"] == "猪皮"
    assert so["lines"][1]["product_code"] == "21L533-25"  # 合并型号向前填充
    assert so["lines"][2]["product_code"] == "21L527-20"
    assert so["lines"][2]["notes"] and "后拉链" in so["lines"][2]["notes"]
    qty_sum = sum(it["qty"] for ln in so["lines"] for it in ln["items"])
    assert qty_sum == 51


def test_parse_generated_template():
    content = build_sales_order_import_template_bytes()
    sheets = parse_sales_order_workbook(content)
    assert len(sheets) == 1
    so = sheets[0]
    assert so["order_no"] == "SO示例001"
    assert so["customer_name"] == "示例客户"
    assert len(so["lines"]) == 2
    assert so["lines"][1]["product_code"] == "OP-001"
