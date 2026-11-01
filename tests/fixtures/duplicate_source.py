def calculate_total(items):
    total = 0
    for item in items:
        value = item.price * item.quantity
        if value > 0:
            total += value
    if total < 0:
        return 0
    return total


def unrelated():
    return 1
