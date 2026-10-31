from __future__ import annotations


def format_inr(paise: int) -> str:
    """Format integer paise as ₹ with Indian digit grouping, e.g. 1850000 -> '₹18,500.00'."""
    sign = "-" if paise < 0 else ""
    rupees, rem = divmod(abs(paise), 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    return f"{sign}₹{digits}.{rem:02d}"
