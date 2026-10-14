"""采购单 Excel 导出：版式对齐打印预览（供应商联 / 可选内部联）。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

import qrcode
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

INK = "111111"
MUTED = "555555"
HEADER_BG = "F3F4F6"
LINE = "333333"
DRAFT = "C45656"

thin_side = Side(style="thin", color=LINE)
thin = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
money_fmt = "0.00"


def _font(bold: bool = False, size: int = 11, color: str = INK) -> Font:
    return Font(name="微软雅黑", bold=bold, size=size, color=color)


def _align(h: str = "left", v: str = "center", wrap: bool = False) -> Alignment:
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)


def _fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)


def _set_widths(ws: Worksheet, widths: dict[int, float]) -> None:
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w


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


def _qr_image(url: str, size_px: int = 120) -> XLImage | None:
    if not url:
        return None
    try:
        img = qrcode.make(url)
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        xl = XLImage(buf)
        xl.width = size_px
        xl.height = size_px
        return xl
    except Exception:
        return None


def _is_draft(detail: dict) -> bool:
    return str(detail.get("status") or "") == "draft"


def _line_purchase_qty(ln: dict, draft: bool) -> Decimal:
    """待下单时损耗尚未并进数量；已下单后数量已含损耗，不能再加一次。"""
    qty = Decimal(str(ln.get("qty") or 0))
    if not draft:
        return qty
    return qty + Decimal(str(ln.get("loss_qty") or 0))


def _money(v: Decimal) -> float:
    return float(Decimal(str(v)).quantize(Decimal("0.01")))


def _qty_num(v: Decimal) -> int | float:
    if v == v.to_integral_value():
        return int(v)
    return float(v)


def _size_labels(lines: list[dict]) -> list[str]:
    items: list[tuple[str, int]] = []
    seen: set[str] = set()
    for ln in lines:
        raw = ln.get("size_value")
        if raw is None or str(raw).strip() == "":
            continue
        label = str(raw).strip()
        if label in seen:
            continue
        seen.add(label)
        items.append((label, int(ln.get("size_sort_order") or 0)))
    items.sort(key=lambda x: (x[1], x[0]))
    return [label for label, _ in items]


def _supplier_table_rows(detail: dict) -> tuple[list[str], list[dict]]:
    """同一物料一行；有码数时各码数量进 size_qty。数量为采购数量（含损耗）。"""
    draft = _is_draft(detail)
    lines = list(detail.get("lines") or [])
    sizes = _size_labels(lines)
    groups: dict[int, dict] = {}
    order: list[int] = []
    for ln in lines:
        sp_id = int(ln.get("supplier_product_id") or 0)
        row = groups.get(sp_id)
        if row is None:
            row = {
                "code": _txt(ln.get("supplier_product_code"), ""),
                "name": _txt(ln.get("supplier_product_name")),
                "unit": _txt(ln.get("pricing_unit_name")),
                "qty": Decimal("0"),
                "amount": Decimal("0"),
                "unit_price": Decimal(str(ln.get("unit_price") or 0)),
                "size_qty": {},
            }
            groups[sp_id] = row
            order.append(sp_id)
        buy = _line_purchase_qty(ln, draft)
        price = Decimal(str(ln.get("unit_price") or 0))
        row["qty"] += buy
        row["amount"] += buy * price
        size = ln.get("size_value")
        if size is not None and str(size).strip():
            label = str(size).strip()
            row["size_qty"][label] = row["size_qty"].get(label, Decimal("0")) + buy
    if not lines:
        for ln in detail.get("summary_lines") or []:
            buy = _line_purchase_qty(ln, draft)
            price = Decimal(str(ln.get("unit_price") or 0))
            order.append(int(ln.get("supplier_product_id") or len(order)))
            groups[order[-1]] = {
                "code": _txt(ln.get("supplier_product_code"), ""),
                "name": _txt(ln.get("supplier_product_name")),
                "unit": _txt(ln.get("pricing_unit_name")),
                "qty": buy,
                "amount": Decimal(str(ln.get("amount") or 0)) if not draft else buy * price,
                "unit_price": price,
                "size_qty": {},
            }
    rows = [groups[i] for i in order]
    rows.sort(key=lambda x: (x.get("code") or "", x.get("name") or ""))
    return sizes, rows


def _style_header(cell, *, right: bool = False, center: bool = False) -> None:
    cell.font = _font(True, 11)
    cell.fill = _fill(HEADER_BG)
    cell.border = thin
    if center:
        cell.alignment = _align("center")
    else:
        cell.alignment = _align("right" if right else "left")


def _write_supplier_sheet(
    ws: Worksheet,
    detail: dict,
    *,
    public_url: str | None,
) -> None:
    sizes, table_rows = _supplier_table_rows(detail)
    last_col = 6 + len(sizes)
    widths = {1: 16, 2: 28, 3: 10}
    for i in range(len(sizes)):
        widths[4 + i] = 8
    widths[last_col - 2] = 12
    widths[last_col - 1] = 12
    widths[last_col] = 14
    ws.sheet_view.showGridLines = False
    _set_widths(ws, widths)

    is_draft = _is_draft(detail)
    row = 1
    if is_draft:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_col)
        cell = ws.cell(row, 1, "【待下单】未正式下单，仅供内部参考")
        cell.font = _font(True, 12, DRAFT)
        cell.alignment = _align("center")
        row = 2

    # 买方抬头 + 二维码
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(4, last_col - 2))
    c = ws.cell(row, 1, _txt(detail.get("buyer_name")))
    c.font = _font(True, 16)
    c.alignment = _align("left", "center")
    ws.row_dimensions[row].height = 24
    buyer_row = row

    qr = _qr_image(public_url or "")
    if qr:
        ws.add_image(qr, f"{get_column_letter(last_col)}{row}")
        ws.row_dimensions[row].height = 20

    row += 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(4, last_col - 2))
    contact = (
        f"联系人{_txt(detail.get('buyer_contact_person'))}    "
        f"电话{_txt(detail.get('buyer_contact_mobile'))}"
    )
    c = ws.cell(row, 1, contact)
    c.font = _font(False, 10)
    c.alignment = _align("left")

    row += 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(4, last_col - 2))
    c = ws.cell(row, 1, f"地址{_txt(detail.get('buyer_address'))}")
    c.font = _font(False, 10)
    c.alignment = _align("left", wrap=True)

    # 单号标在二维码下方
    po_label_row = buyer_row + 3
    if qr:
        c = ws.cell(po_label_row, last_col, _txt(detail.get("po_no"), ""))
        c.font = _font(False, 9, MUTED)
        c.alignment = _align("center")

    row = max(row + 2, po_label_row + 2)

    meta = [
        (f"采购单号：{_txt(detail.get('po_no'))}", f"协商交货日期：{_txt(detail.get('expected_date'))}"),
        (
            f"供应商：{_txt(detail.get('partner_name'))}",
            f"下单日期：{_date_txt(detail.get('ordered_at'))}",
        ),
        (
            f"联系人：{_txt(detail.get('partner_contact_name'))}  "
            f"{_txt(detail.get('partner_contact_mobile'), '')}".rstrip(),
            "",
        ),
    ]
    for left, right in meta:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        c = ws.cell(row, 1, left)
        c.font = _font(False, 11)
        if right:
            ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=last_col)
            c2 = ws.cell(row, 4, right)
            c2.font = _font(False, 11)
        row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_col)
    c = ws.cell(row, 1, f"供应商地址：{_txt(detail.get('partner_address'))}")
    c.font = _font(False, 11)
    c.alignment = _align("left", wrap=True)
    row += 2

    qty_col = 4 + len(sizes)
    price_col = qty_col + 1
    amount_col = qty_col + 2
    if sizes:
        for col, title in enumerate(["物料编码", "名称", "单位"], 1):
            ws.merge_cells(start_row=row, start_column=col, end_row=row + 1, end_column=col)
            _style_header(ws.cell(row, col, title))
        ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=3 + len(sizes))
        _style_header(ws.cell(row, 4, "码数"), center=True)
        for i, size in enumerate(sizes):
            _style_header(ws.cell(row + 1, 4 + i, size), center=True)
        for col, title in ((qty_col, "数量"), (price_col, "单价"), (amount_col, "金额")):
            ws.merge_cells(start_row=row, start_column=col, end_row=row + 1, end_column=col)
            _style_header(ws.cell(row, col, title), center=(col == qty_col), right=(col != qty_col))
        header_row = row + 1
        row += 2
    else:
        headers = ["物料编码", "名称", "单位", "数量", "单价", "金额"]
        for col, h in enumerate(headers, 1):
            _style_header(ws.cell(row, col, h), center=(col == 4), right=(col >= 5))
        header_row = row
        row += 1

    for ln in table_rows:
        vals: list[Any] = [ln["code"], ln["name"], ln["unit"]]
        for size in sizes:
            qty = ln["size_qty"].get(size)
            vals.append(_qty_num(qty) if qty is not None else None)
        vals.extend([
            _qty_num(ln["qty"]),
            _money(ln["unit_price"]),
            _money(ln["amount"]),
        ])
        for col, val in enumerate(vals, 1):
            cell = ws.cell(row, col, val if val is not None else "—")
            cell.font = _font(False, 11)
            cell.border = thin
            if col >= 4:
                center = col < price_col
                cell.alignment = _align("center" if center else "right")
                if isinstance(val, (int, float)) and col >= price_col:
                    cell.number_format = money_fmt
                elif isinstance(val, (int, float)):
                    cell.number_format = "0.##"
            else:
                cell.alignment = _align("left")
        row += 1

    if not table_rows:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_col)
        cell = ws.cell(row, 1, "（无明细）")
        cell.border = thin
        cell.alignment = _align("center")
        row += 1

    row += 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_col)
    total = sum((Decimal(str(x["amount"])) for x in table_rows), Decimal("0"))
    cell = ws.cell(row, 1, f"合计金额：¥{_money(total):.2f}")
    cell.font = _font(True, 12)
    cell.alignment = _align("right")
    row += 2

    note = f"备注：{_txt(detail.get('notes'), '无')}"
    tax = _txt(detail.get("tax_note"), "")
    if tax and tax != "—":
        note = f"{note}\n{tax}"
    ws.merge_cells(start_row=row, start_column=1, end_row=row + 1, end_column=last_col)
    cell = ws.cell(row, 1, note)
    cell.font = _font(False, 10, MUTED)
    cell.alignment = _align("left", "top", wrap=True)
    ws.row_dimensions[row].height = 18
    ws.row_dimensions[row + 1].height = 18
    row += 3

    # 签字区
    ws.cell(row, 1, "采购方签字/盖章").font = _font(False, 10, MUTED)
    ws.cell(row, 4, "供应商签字/盖章").font = _font(False, 10, MUTED)
    row += 2
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
    ws.cell(row, 1, "________________").font = _font(False, 11)
    ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=5)
    ws.cell(row, 4, "________________").font = _font(False, 11)
    row += 1
    ws.cell(row, 1, "日期：________").font = _font(False, 10, MUTED)
    ws.cell(row, 4, "日期：________").font = _font(False, 10, MUTED)

    # 打印区域大致覆盖内容
    ws.print_title_rows = f"1:{header_row}"
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0


def _internal_table_rows(detail: dict) -> tuple[list[str], list[dict]]:
    """同一物料、同一订单合并为一行，码数拆列。数量含损耗。"""
    draft = _is_draft(detail)
    lines = list(detail.get("lines") or [])
    sizes = _size_labels(lines)
    groups: dict[tuple, dict] = {}
    order: list[tuple] = []
    for ln in lines:
        key = (int(ln.get("supplier_product_id") or 0), _txt(ln.get("order_no"), ""))
        row = groups.get(key)
        if row is None:
            row = {
                "code": _txt(ln.get("supplier_product_code"), ""),
                "name": _txt(ln.get("supplier_product_name")),
                "unit": _txt(ln.get("pricing_unit_name")),
                "order_no": key[1],
                "qty": Decimal("0"),
                "unit_price": Decimal(str(ln.get("unit_price") or 0)),
                "size_qty": {},
            }
            groups[key] = row
            order.append(key)
        buy = _line_purchase_qty(ln, draft)
        row["qty"] += buy
        size = ln.get("size_value")
        if size is not None and str(size).strip():
            label = str(size).strip()
            row["size_qty"][label] = row["size_qty"].get(label, Decimal("0")) + buy
    return sizes, [groups[k] for k in order]


def _write_internal_sheet(ws: Worksheet, detail: dict) -> None:
    sizes, table_rows = _internal_table_rows(detail)
    last_col = 6 + len(sizes)
    widths = {1: 16, 2: 28, 3: 10, 4: 14}
    for i in range(len(sizes)):
        widths[5 + i] = 8
    widths[last_col - 1] = 12
    widths[last_col] = 12
    ws.sheet_view.showGridLines = False
    _set_widths(ws, widths)

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    c = ws.cell(1, 1, f"采购单内部联 · {_txt(detail.get('po_no'))}")
    c.font = _font(True, 14)
    c.alignment = _align("left")

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_col)
    c = ws.cell(2, 1, "以下为分订单明细，仅内部跟单/到货回写使用，勿发给供应商。")
    c.font = _font(False, 10, MUTED)

    qty_col = 5 + len(sizes)
    price_col = qty_col + 1
    if sizes:
        for col, title in enumerate(["物料编码", "名称", "单位", "订单"], 1):
            ws.merge_cells(start_row=4, start_column=col, end_row=5, end_column=col)
            _style_header(ws.cell(4, col, title))
        ws.merge_cells(start_row=4, start_column=5, end_row=4, end_column=4 + len(sizes))
        _style_header(ws.cell(4, 5, "码数"), center=True)
        for i, size in enumerate(sizes):
            _style_header(ws.cell(5, 5 + i, size), center=True)
        ws.merge_cells(start_row=4, start_column=qty_col, end_row=5, end_column=qty_col)
        _style_header(ws.cell(4, qty_col, "数量"), center=True)
        ws.merge_cells(start_row=4, start_column=price_col, end_row=5, end_column=price_col)
        _style_header(ws.cell(4, price_col, "单价"), right=True)
        row = 6
    else:
        headers = ["物料编码", "名称", "单位", "订单", "数量", "单价"]
        for col, h in enumerate(headers, 1):
            _style_header(ws.cell(4, col, h), center=(col == 5), right=(col == 6))
        row = 5

    for ln in table_rows:
        vals: list[Any] = [ln["code"], ln["name"], ln["unit"], ln["order_no"]]
        for size in sizes:
            qty = ln["size_qty"].get(size)
            vals.append(_qty_num(qty) if qty is not None else None)
        vals.extend([_qty_num(ln["qty"]), _money(ln["unit_price"])])
        for col, val in enumerate(vals, 1):
            cell = ws.cell(row, col, val if val is not None else "—")
            cell.font = _font(False, 11)
            cell.border = thin
            if col >= 5:
                center = col < price_col
                cell.alignment = _align("center" if center else "right")
                if isinstance(val, (int, float)) and col == price_col:
                    cell.number_format = money_fmt
                elif isinstance(val, (int, float)):
                    cell.number_format = "0.##"
            else:
                cell.alignment = _align("left")
        row += 1

    if not table_rows:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_col)
        cell = ws.cell(row, 1, "（无明细）")
        cell.border = thin
        cell.alignment = _align("center")


def build_purchase_order_workbook(
    detail: dict,
    *,
    include_internal: bool = False,
    public_url: str | None = None,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "供应商联"
    _write_supplier_sheet(ws, detail, public_url=public_url)

    if include_internal:
        ws2 = wb.create_sheet("内部联")
        _write_internal_sheet(ws2, detail)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
