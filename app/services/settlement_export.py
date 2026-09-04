"""对账单 Excel 导出：版式对齐打印预览（客户/供应商/外协通用）。"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.worksheet.worksheet import Worksheet

from PIL import Image as PILImage

from app.config import get_settings

_CUSTOMER_TEMPLATE_PATH = Path(__file__).parent / "templates" / "customer_statement.xlsx"

INK = "111111"
MUTED = "555555"
HEADER_BG = "F3F4F6"
LINE = "333333"

thin_side = Side(style="thin", color=LINE)
thin = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)


def _font(bold: bool = False, size: int = 11, color: str = INK) -> Font:
    return Font(name="微软雅黑", bold=bold, size=size, color=color)


def _align(h: str = "left", v: str = "center", wrap: bool = False) -> Alignment:
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)


def _fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)


def _txt(v: Any, default: str = "—") -> str:
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def _date_txt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).replace("T", " ")
    return s[:10] if s else "—"


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(Decimal(str(v)))
    except Exception:
        return None


def _money(v: Any) -> float:
    value = _num(v)
    return round(value, 2) if value is not None else 0.0


def _set_widths(ws: Worksheet, widths: dict[int, float]) -> None:
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w


def _merge_styled(
    ws: Worksheet,
    start_row: int,
    start_col: int,
    end_row: int,
    end_col: int,
    value: Any = None,
    *,
    font: Font | None = None,
    alignment: Alignment | None = None,
    border: Border | None = None,
    fill: PatternFill | None = None,
) -> None:
    """合并单元格并给区域内所有单元格应用样式。

    openpyxl 合并后只有左上角保留样式，其余区域无边框；
    这里显式遍历整个区域补齐边框/字体/对齐，保证打印与预览都有框线。
    """
    ws.merge_cells(
        start_row=start_row, start_column=start_col,
        end_row=end_row, end_column=end_col,
    )
    for r in range(start_row, end_row + 1):
        for c in range(start_col, end_col + 1):
            cell = ws.cell(r, c)
            if border is not None:
                cell.border = border
            if font is not None:
                cell.font = font
            if alignment is not None:
                cell.alignment = alignment
            if fill is not None:
                cell.fill = fill
    if value is not None:
        ws.cell(start_row, start_col, value)


def _period_label(detail: dict) -> str:
    start = str(detail.get("period_start") or "")
    end = str(detail.get("period_end") or "")
    start_parts = start.split("-")
    end_parts = end.split("-")
    if len(start_parts) == 3 and len(end_parts) == 3:
        try:
            import calendar

            start_year, start_month, start_day = map(int, start_parts)
            end_year, end_month, end_day = map(int, end_parts)
            month_last_day = calendar.monthrange(start_year, start_month)[1]
            if (
                start_year == end_year
                and start_month == end_month
                and start_day == 1
                and end_day == month_last_day
            ):
                return f"{start_year}年{start_month}月"
            if start_year == end_year:
                return (
                    f"{start_month:02d}/{start_day:02d}–"
                    f"{end_month:02d}/{end_day:02d}"
                )
        except ValueError:
            pass
    return f"{start}–{end}" if start and end else (start or end or "—")


def _display_doc_no(line: dict) -> str:
    value = str(line.get("document_no") or "").strip()
    source_type = line.get("source_type")
    if source_type == "opening_balance":
        return "期初余额"
    if re.match(r"^(AR|AP)-\d+$", value, re.IGNORECASE):
        return "—"
    if re.match(r"^SK-\d+$", value, re.IGNORECASE):
        return "收款记录"
    if re.match(r"^FK-\d+$", value, re.IGNORECASE):
        return "付款记录"
    if value:
        return value
    if source_type == "payment":
        return "收款记录"
    if source_type == "supplier_payment":
        return "付款记录"
    return "—"


def _flatten_lines(detail: dict, item_key: str) -> list[dict]:
    """按打印预览口径展开明细行：每货品项一行，金额按比例分配。"""
    rows: list[dict] = []
    for line in detail.get("lines") or []:
        source_items = line.get(item_key) or []
        items: list[dict | None] = source_items if source_items else [None]
        allocated = 0.0
        for item_index, item in enumerate(items):
            is_last = item_index == len(items) - 1
            line_debit = _money(line.get("debit_amount"))
            if item:
                debit = (
                    line_debit - allocated
                    if is_last
                    else min(_money(item.get("amount")), line_debit - allocated)
                )
            else:
                debit = line_debit
            allocated += debit
            credit = _money(line.get("credit_amount")) if item_index == 0 else 0.0
            rows.append(
                {
                    "document_no": line.get("document_no"),
                    "business_date": line.get("business_date"),
                    "source_type": line.get("source_type"),
                    "item": item,
                    "debit": debit,
                    "credit": credit,
                    "first_item": item_index == 0,
                }
            )
    return rows


def _material_text(row: dict, subcontract: bool) -> str:
    item = row.get("item")
    if item:
        if subcontract:
            if item.get("process_name"):
                return str(item["process_name"])
            return _txt(item.get("customer_sku") or item.get("item_code"))
        if item.get("item_name"):
            return str(item["item_name"])
    source_type = row.get("source_type")
    if source_type == "supplier_payment":
        return "本期付款"
    if source_type == "opening_balance":
        return "上期余额"
    return _txt(row.get("description"), "历史应付" if not subcontract else "历史外协应付")


def _spec_text(item: dict | None) -> str:
    if not item:
        return "—"
    parts = []
    if item.get("color_name"):
        parts.append(str(item["color_name"]))
    for size in item.get("size_breakdown") or []:
        value = size.get("size_value")
        if value:
            parts.append(str(value))
    return " / ".join(parts) or "—"


def _supplier_columns(subcontract: bool) -> list[tuple[str, float, str]]:
    return [
        ("验收日期" if subcontract else "到货日期", 12, "date"),
        ("外协单号" if subcontract else "采购单号", 15, "doc_no"),
        ("加工工序" if subcontract else "物料名称", 18, "text"),
        ("鞋款/客户型号" if subcontract else "物料编码", 13, "text"),
        ("颜色/码数" if subcontract else "颜色/规格", 13, "text"),
        ("单位", 7, "text"),
        ("合格验收数量" if subcontract else "到货数量", 12, "num"),
        ("加工单价" if subcontract else "采购单价", 9, "num"),
        ("应付/付款金额", 13, "num"),
    ]


def _money_to_chinese_upper(value: Any) -> str:
    raw = _num(value)
    if raw is None or raw != raw or raw in (float("inf"), float("-inf")):
        return "人民币零元整"
    prefix = "负" if raw < 0 else ""
    fixed = f"{abs(raw):.2f}"
    integer_part, decimal_part = fixed.split(".")
    digits = ["零", "壹", "贰", "叁", "肆", "伍", "陆", "柒", "捌", "玖"]
    units = ["", "拾", "佰", "仟"]
    group_units = ["", "万", "亿", "兆"]

    def integer_to_chinese(number: int) -> str:
        if number == 0:
            return "零"
        result = ""
        group_index = 0
        need_zero = False
        while number > 0:
            section = number % 10000
            if section == 0:
                if result:
                    need_zero = True
            else:
                section_value = section
                section_text = ""
                unit_index = 0
                zero_pending = False
                while section_value > 0:
                    digit = section_value % 10
                    if digit == 0:
                        if section_text:
                            zero_pending = True
                    else:
                        section_text = (
                            f"{digits[digit]}{units[unit_index]}"
                            f"{'零' if zero_pending else ''}{section_text}"
                        )
                        zero_pending = False
                    unit_index += 1
                    section_value //= 10
                if need_zero and result:
                    result = f"零{result}"
                result = f"{section_text}{group_units[group_index]}{result}"
                need_zero = section < 1000
            number //= 10000
            group_index += 1
        return result

    integer_text = integer_to_chinese(int(integer_part))
    jiao = int(decimal_part[0])
    fen = int(decimal_part[1])
    fraction = f"{digits[jiao]}角" if jiao else ""
    fraction += f"{digits[fen]}分" if fen else ""
    fraction = fraction or "整"
    return f"人民币{prefix}{integer_text}元{fraction}"


def _signature_labels(detail: dict) -> tuple[str, str]:
    is_customer = detail.get("direction") == "customer"
    partner = _txt(detail.get("partner_full_name") or detail.get("partner_name"), "客户")
    issuer = _txt(detail.get("issuer_name"), "本厂")
    if is_customer:
        return f"客户（{partner}）确认", f"供方（{issuer}）确认"
    return "供应商确认", "采购方（本厂）确认"


def _resolve_image_path(image_url: Any) -> Path | None:
    """把 /uploads/xxx.jpg 解析为本地文件；无法解析或不存在返回 None。"""
    if not image_url:
        return None
    name = str(image_url).rsplit("/", 1)[-1].split("?", 1)[0].split("#", 1)[0]
    if not name:
        return None
    path = Path(get_settings().uploads_dir) / name
    return path if path.is_file() else None


def _insert_image(ws: Worksheet, path: Path, row: int, col: int) -> None:
    """向指定单元格插入 34×34 缩略图（与页面打印缩略图尺寸一致）。

    Excel/openpyxl 不支持 webp（mimetypes 无映射且兼容性差），
    统一用 Pillow 转成 PNG 字节后再插入。
    """
    try:
        raw = path.read_bytes()
        pil_img = PILImage.open(BytesIO(raw))
        if (pil_img.format or "").upper() != "PNG":
            out = BytesIO()
            pil_img.convert("RGBA").save(out, format="PNG")
            raw = out.getvalue()
        img = XLImage(BytesIO(raw))
        img.width = 34
        img.height = 34
        ws.add_image(img, f"{get_column_letter(col)}{row}")
        # 行高 44 点 ≈ 59px，34px 图片四周留白，不会顶出单元格边框
        ws.row_dimensions[row].height = 44
    except Exception:
        pass  # 图片损坏或格式不支持时静默降级为无图


def _apply_print_setup(ws: Worksheet, total_cols: int, last_row: int) -> None:
    """A4 横向；明细列为动态（码数数量不定），统一缩放到一页宽。"""
    ws.print_area = f"A1:{get_column_letter(total_cols)}{last_row}"
    ws.print_options.horizontalCentered = True
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_margins.left = 0.3
    ws.page_margins.right = 0.3
    ws.page_margins.top = 0.4
    ws.page_margins.bottom = 0.4
    ws.page_margins.header = 0
    ws.page_margins.footer = 0


def _find_soffice() -> str | None:
    found = shutil.which("soffice")
    if found:
        return found
    for path in ("/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice"):
        if Path(path).is_file():
            return path
    return None


def workbook_to_pdf(xlsx_bytes: bytes) -> bytes:
    """用 LibreOffice headless 把 xlsx 转成 pdf。"""
    soffice = _find_soffice()
    if not soffice:
        raise RuntimeError("LibreOffice not found")
    env_home = tempfile.mkdtemp(prefix="lo_home_")
    with tempfile.TemporaryDirectory() as tmp:
        xlsx_path = Path(tmp) / "input.xlsx"
        xlsx_path.write_bytes(xlsx_bytes)
        subprocess.run(
            [
                soffice,
                "--headless",
                "--norestore",
                f"-env:UserInstallation=file://{env_home}",
                "--convert-to", "pdf",
                "--outdir", tmp,
                str(xlsx_path),
            ],
            check=True, capture_output=True, timeout=30,
        )
        pdf_path = Path(tmp) / "input.pdf"
        return pdf_path.read_bytes()


def _write_title(ws: Worksheet, detail: dict, total_cols: int) -> None:
    _merge_styled(
        ws, 1, 1, 1, total_cols,
        "客户对账单" if detail.get("direction") == "customer" else "往来对账单",
        font=_font(True, 16),
        alignment=_align("center"),
    )


def _write_statement_no(ws: Worksheet, detail: dict, total_cols: int) -> int:
    _merge_styled(
        ws, 2, 1, 2, total_cols,
        f"对账单号：{_txt(detail.get('statement_no'))}",
        font=_font(False, 10, MUTED),
        alignment=_align("left"),
    )
    return 3


def _write_info_rows(ws: Worksheet, detail: dict, total_cols: int) -> int:
    row = 3
    half = max(2, total_cols // 2)
    is_customer = detail.get("direction") == "customer"
    partner_label = "客户" if is_customer else "往来单位"
    info_lines = [
        (
            f"{partner_label}：{_txt(detail.get('partner_full_name') or detail.get('partner_name'))}",
            f"月份：{_period_label(detail)}",
        ),
        (
            f"联系人：{_txt(detail.get('partner_contact_name'))} {_txt(detail.get('partner_contact_mobile'), '')}",
            f"客户地址：{_txt(detail.get('partner_address'))}",
        ),
        (
            f"开户行：{_txt(detail.get('issuer_bank_name'))}",
            f"账号：{_txt(detail.get('issuer_bank_account'))}",
        ),
        (
            f"户名：{_txt(detail.get('issuer_bank_account_name') or detail.get('issuer_name'))}",
            "",
        ),
    ]
    for left, right in info_lines:
        _merge_styled(
            ws, row, 1, row, half, left,
            font=_font(False, 10), alignment=_align("left"), border=thin,
        )
        if right:
            _merge_styled(
                ws, row, half + 1, row, total_cols, right,
                font=_font(False, 10), alignment=_align("left"), border=thin,
            )
        row += 1
    return row


def _write_summary(ws: Worksheet, detail: dict, total_cols: int, row: int) -> int:
    is_customer = detail.get("direction") == "customer"
    remaining_label = "当前待收" if is_customer else "当前待付"
    summary_rows = [
        ("上期欠款", _money(detail.get("opening_balance")), False),
        ("退货/扣款", _money(detail.get("adjustment_amount")), False),
        (
            f"本期货款合计 + 上期欠款 − 退货/扣款 = {remaining_label}",
            _money(detail.get("remaining_amount")),
            True,
        ),
    ]
    for label, amount, bold in summary_rows:
        _merge_styled(
            ws, row, 1, row, total_cols - 2, label,
            font=_font(bold, 10),
            alignment=_align("right" if bold else "left"),
            border=thin,
        )
        _merge_styled(
            ws, row, total_cols - 1, row, total_cols, amount,
            font=_font(bold, 10), alignment=_align("right"), border=thin,
        )
        row += 1
    return row


def _write_amount_upper(ws: Worksheet, detail: dict, total_cols: int, row: int) -> int:
    _merge_styled(
        ws, row, 1, row, total_cols,
        f"对账余额（大写）：{_money_to_chinese_upper(detail.get('closing_balance'))} "
        f"小写：¥{_money(detail.get('closing_balance')):,.2f}",
        font=_font(True, 11),
        alignment=_align("left"),
        border=thin,
    )
    return row + 1


def _write_confirmation(ws: Worksheet, detail: dict, total_cols: int, row: int) -> int:
    partner_label, issuer_label = _signature_labels(detail)
    half = max(2, total_cols // 2)
    blocks = [
        (1, half, partner_label),
        (half + 1, total_cols, issuer_label),
    ]
    for start_col, end_col, label in blocks:
        _merge_styled(
            ws, row, start_col, row, end_col, label,
            font=_font(True, 10), alignment=_align("left"), border=thin,
        )
        for offset, text in enumerate(("签字/盖章：", "日期：______年____月____日"), start=1):
            _merge_styled(
                ws, row + offset, start_col, row + offset, end_col, text,
                font=_font(False, 10), alignment=_align("left"), border=thin,
            )
    return row + 3


def _write_empty_hint(ws: Worksheet, row: int, total_cols: int) -> int:
    _merge_styled(
        ws, row, 1, row, total_cols, "本期无明细",
        font=_font(False, 10, MUTED),
        alignment=_align("center"),
        border=thin,
    )
    return row + 1


def _write_totals_row(ws: Worksheet, row: int, total_cols: int, label: str, total: float) -> int:
    _merge_styled(
        ws, row, 1, row, total_cols - 1, label,
        font=_font(True, 10), alignment=_align("right"), border=thin,
    )
    cell = ws.cell(row, total_cols, round(total, 2))
    cell.font = _font(True, 10)
    cell.border = thin
    cell.alignment = _align("right")
    return row + 1


# ── 客户对账单：基于模版填充 ──


def _copy_cell_style(src, dst) -> None:
    """Copy visual style (font/fill/border/alignment/number_format) between cells."""
    if src.font:
        dst.font = src.font.copy()
    if src.fill:
        dst.fill = src.fill.copy()
    if src.border:
        dst.border = src.border.copy()
    if src.alignment:
        dst.alignment = src.alignment.copy()
    if src.number_format:
        dst.number_format = src.number_format


def _build_customer_workbook(detail: dict) -> bytes:
    """基于模版生成客户对账单 Excel。"""
    total_cols = 12

    tpl_wb = load_workbook(_CUSTOMER_TEMPLATE_PATH)
    tpl_ws = tpl_wb.active
    ws = tpl_wb.active
    ws.title = "客户对账单"

    # save template row 7 cell styles for data rows
    tpl_data_styles = []
    for col in range(1, total_cols + 1):
        tpl_data_styles.append(tpl_ws.cell(7, col))

    # clear template data rows and footer (row 7+)
    to_unmerge = [
        str(m) for m in ws.merged_cells.ranges
        if m.min_row >= 7
    ]
    for rng in to_unmerge:
        ws.unmerge_cells(rng)
    for row_cells in ws.iter_rows(min_row=7, max_row=tpl_ws.max_row):
        for cell in row_cells:
            cell.value = None

    # ── fill header variables ──
    ws.cell(1, 1).value = "客户对账单"
    ws.cell(2, 1).value = f"对账单号：{_txt(detail.get('statement_no'))}"
    ws.cell(3, 1).value = f"客户：{_txt(detail.get('partner_full_name') or detail.get('partner_name'))}"
    ws.cell(3, 7).value = f"月份：{_period_label(detail)}"
    ws.cell(4, 1).value = (
        f"联系人：{_txt(detail.get('partner_contact_name'))} "
        f"{_txt(detail.get('partner_contact_mobile'), '')}"
    )
    ws.cell(4, 7).value = f"客户地址：{_txt(detail.get('partner_address'))}"

    # ── build flat item rows ──
    item_rows: list[dict] = []
    for line in detail.get("lines") or []:
        shipment_items = line.get("shipment_items") or []
        if not shipment_items:
            continue
        for item in shipment_items:
            item_rows.append({
                "date": line.get("business_date"),
                "shipment_no": item.get("shipment_no"),
                "sales_order_no": item.get("sales_order_no"),
                "item": item,
                "item_amount": _money(item.get("amount")),
            })

    # group consecutive rows by shipment_no for cell merging
    groups: list[list[int]] = []
    for idx, row_data in enumerate(item_rows):
        sno = row_data.get("shipment_no")
        if (
            groups
            and sno
            and sno == item_rows[groups[-1][0]].get("shipment_no")
        ):
            groups[-1].append(idx)
        else:
            groups.append([idx])

    # ── write data rows ──
    row = 7
    for group in groups:
        start_row = row
        group_size = len(group)
        for i, idx in enumerate(group):
            ir = item_rows[idx]
            item = ir.get("item")
            ws.row_dimensions[row].height = 23

            for col in range(1, total_cols + 1):
                _copy_cell_style(tpl_data_styles[col - 1], ws.cell(row, col))

            if i == 0:
                ws.cell(row, 1).value = _date_txt(ir["date"])
                ws.cell(row, 2).value = _txt(ir.get("shipment_no"))

            ws.cell(row, 3).value = _txt(ir.get("sales_order_no"))

            if item:
                ws.cell(row, 4).value = _txt(item.get("product_code"))
                image_path = _resolve_image_path(item.get("image_url"))
                if image_path:
                    _insert_image(ws, image_path, row, 5)
                ws.cell(row, 6).value = _txt(item.get("color_name"))
                ws.cell(row, 7).value = _txt(item.get("customer_sku"))
                ws.cell(row, 8).value = _txt(item.get("brand_name"))
                ws.cell(row, 9).value = _num(item.get("carton_count"))
                ws.cell(row, 10).value = _num(item.get("qty"))
                ws.cell(row, 11).value = _num(item.get("unit_price"))
                ws.cell(row, 12).value = ir["item_amount"]

            row += 1

        if group_size > 1:
            for merge_col in (1, 2):
                ws.merge_cells(
                    start_row=start_row, start_column=merge_col,
                    end_row=start_row + group_size - 1, end_column=merge_col,
                )
                for r in range(start_row, start_row + group_size):
                    ws.cell(r, merge_col).border = thin
                    ws.cell(r, merge_col).font = _font(False, 9)
                    ws.cell(r, merge_col).alignment = _align("center")

    if not item_rows:
        for col in range(1, total_cols + 1):
            _copy_cell_style(tpl_data_styles[col - 1], ws.cell(row, col))
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=total_cols)
        ws.cell(row, 1).value = "本期无出货明细"
        ws.cell(row, 1).alignment = _align("center")
        ws.cell(row, 1).font = _font(False, 10, MUTED)
        row += 1

    # ── footer: totals row ──
    net_total = _money(detail.get("current_amount"))
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=total_cols - 1)
    ws.cell(row, 1).value = "本期货款合计"
    ws.cell(row, 1).font = _font(True, 10)
    ws.cell(row, 1).alignment = _align("right")
    ws.cell(row, 1).border = thin
    for c in range(2, total_cols):
        ws.cell(row, c).border = thin
    ws.cell(row, total_cols).value = round(net_total, 2)
    ws.cell(row, total_cols).font = _font(True, 10)
    ws.cell(row, total_cols).alignment = _align("right")
    ws.cell(row, total_cols).border = thin
    row += 1

    # ── footer: summary section (blank row + 3 summary rows) ──
    row += 1
    opening = _money(detail.get("opening_balance"))
    adjustment = _money(detail.get("adjustment_amount"))
    remaining = _money(detail.get("remaining_amount"))

    summary_rows = [
        ("上期欠款", opening, False),
        ("退货/扣款", adjustment, False),
        ("本期货款合计 + 上期欠款 − 退货/扣款 = 当前待收货款总计", remaining, True),
    ]
    for label, amount, bold in summary_rows:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=total_cols - 2)
        ws.cell(row, 1).value = label
        ws.cell(row, 1).font = _font(bold, 10)
        ws.cell(row, 1).alignment = _align("right")
        ws.cell(row, 1).border = thin
        for c in range(2, total_cols - 1):
            ws.cell(row, c).border = thin
        ws.merge_cells(start_row=row, start_column=total_cols - 1, end_row=row, end_column=total_cols)
        ws.cell(row, total_cols - 1).value = amount
        ws.cell(row, total_cols - 1).font = _font(bold, 10)
        ws.cell(row, total_cols - 1).alignment = _align("right")
        ws.cell(row, total_cols - 1).border = thin
        ws.cell(row, total_cols).border = thin
        row += 1

    # ── footer: Chinese uppercase amount ──
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=total_cols)
    ws.cell(row, 1).value = f"货款总计（大写）：{_money_to_chinese_upper(detail.get('remaining_amount'))}"
    ws.cell(row, 1).font = _font(True, 11)
    ws.cell(row, 1).alignment = _align("left")
    ws.cell(row, 1).border = thin
    for c in range(2, total_cols + 1):
        ws.cell(row, c).border = thin
    row += 1

    # ── footer: bank info row ──
    ws.cell(row, 1).value = (
        f"收款人：{_txt(detail.get('issuer_bank_account_name') or detail.get('issuer_name'))}"
    )
    ws.cell(row, 1).font = _font(False, 11)
    ws.cell(row, 3).value = f"收款账号：{_txt(detail.get('issuer_bank_account'))}"
    ws.cell(row, 3).font = _font(False, 11)
    ws.cell(row, 5).value = f"开户行：{_txt(detail.get('issuer_bank_name'))}"
    ws.cell(row, 5).font = _font(False, 11)
    row += 1

    # ── footer: confirmation section (3-row merged blocks) ──
    partner_label, issuer_label = _signature_labels(detail)
    half = total_cols // 2
    partner_text = f"\n{partner_label}\n\n签字/盖章：\n\n日期：______年____月____日"
    issuer_text = f"\n{issuer_label}\n\n签字/盖章：\n\n日期：______年____月____日"
    ws.merge_cells(start_row=row, start_column=1, end_row=row + 2, end_column=half)
    ws.cell(row, 1).value = partner_text
    ws.cell(row, 1).font = _font(True, 10)
    ws.cell(row, 1).alignment = _align(v="center", wrap=True)
    ws.cell(row, 1).border = thin
    ws.merge_cells(start_row=row, start_column=half + 1, end_row=row + 2, end_column=total_cols)
    ws.cell(row, half + 1).value = issuer_text
    ws.cell(row, half + 1).font = _font(True, 10)
    ws.cell(row, half + 1).alignment = _align(v="center", wrap=True)
    ws.cell(row, half + 1).border = thin
    for r in range(row, row + 3):
        for c in range(1, total_cols + 1):
            ws.cell(r, c).border = thin
    row += 3

    ws.freeze_panes = ws.cell(7, 1)
    ws.print_title_rows = "$5:$6"
    _apply_print_setup(ws, total_cols, row)

    buf = BytesIO()
    tpl_wb.save(buf)
    return buf.getvalue()


def _write_customer_sheet(ws: Worksheet, detail: dict) -> None:
    """保留兼容接口；实际由 _build_customer_workbook 处理。"""
    pass


def _write_supplier_sheet(ws: Worksheet, detail: dict, subcontract: bool) -> None:
    rows = _flatten_lines(detail, "supplier_items")
    columns = _supplier_columns(subcontract)
    total_cols = len(columns)

    _write_title(ws, detail, total_cols)
    row = _write_statement_no(ws, detail, total_cols)
    row = _write_info_rows(ws, detail, total_cols)
    row += 1  # 空行

    header_row = row
    for col_index, (title, _w, _kind) in enumerate(columns, start=1):
        cell = ws.cell(row, col_index, title)
        cell.font = _font(True, 10)
        cell.fill = _fill(HEADER_BG)
        cell.border = thin
        cell.alignment = _align("center")
    row += 1

    for line in rows:
        item = line.get("item")
        values: list[Any] = [""] * total_cols
        values[0] = _date_txt(line["business_date"]) if line.get("first_item") else ""
        values[1] = _display_doc_no(line) if line.get("first_item") else ""
        if item:
            values[2] = _material_text(line, subcontract)
            values[3] = _txt(item.get("item_code")) if not subcontract else _txt(item.get("customer_sku") or item.get("item_code"))
            values[4] = _spec_text(item)
            values[5] = _txt(item.get("unit_name"))
            values[6] = _num(item.get("qty"))
            values[7] = _num(item.get("unit_price"))
        values[-1] = _money(line["debit"]) - _money(line["credit"])
        for col_index, value in enumerate(values, start=1):
            cell = ws.cell(row, col_index, value if value is not None else "")
            cell.font = _font(False, 10)
            cell.border = thin
            kind = columns[col_index - 1][2]
            cell.alignment = _align("right" if kind == "num" else "left")
        row += 1

    if not rows:
        row = _write_empty_hint(ws, row, total_cols)

    net_total = sum(_money(line["debit"]) - _money(line["credit"]) for line in rows)
    row = _write_totals_row(ws, row, total_cols, "本期合计", net_total)

    row += 1
    row = _write_summary(ws, detail, total_cols, row)
    row += 1
    row = _write_amount_upper(ws, detail, total_cols, row)
    row += 1
    row = _write_confirmation(ws, detail, total_cols, row)

    _set_widths(ws, {index: width for index, (_t, width, _k) in enumerate(columns, start=1)})
    ws.freeze_panes = ws.cell(header_row + 1, 1)
    ws.print_title_rows = f"{header_row}:{header_row}"
    _apply_print_setup(ws, total_cols, row)


def build_statement_workbook(detail: dict) -> bytes:
    direction = detail.get("direction")
    partner_type = detail.get("partner_type")
    if direction == "customer":
        return _build_customer_workbook(detail)

    wb = Workbook()
    ws = wb.active
    if partner_type == "subcontractor":
        ws.title = "外协厂对账单"
        _write_supplier_sheet(ws, detail, subcontract=True)
    else:
        ws.title = "供应商对账单"
        _write_supplier_sheet(ws, detail, subcontract=False)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
