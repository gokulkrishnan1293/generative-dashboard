"""Creates a small demo sales database (SQLite) so the product can be tried end to end."""

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DEMO_DOCUMENTATION = """\
Sales operations glossary (demo company "Northwind Outdoor").

- An order is placed by one customer and handled by one sales rep. Each order has one or more order lines (order_items).
- Revenue = quantity * unit_price * (1 - discount_pct) summed over order lines. unit_price is the price actually charged, in USD.
- Gross margin = revenue - quantity * products.unit_cost.
- Order status lifecycle: pending -> processing -> shipped -> delivered. Cancelled orders do not count toward revenue reporting.
- Customer segment: enterprise (500+ employees), smb, consumer.
- Channel: online store, retail stores, or partner resellers.
- sales_rep_compensation is confidential HR data.
"""

REGIONS = [
    ("North America", "US"), ("Latin America", "BR"), ("Western Europe", "DE"),
    ("Nordics", "SE"), ("Asia Pacific", "SG"), ("Middle East", "AE"),
]
CATEGORIES = {
    "Tents": [("Summit 2P Tent", 180, 349), ("Basecamp 4P Tent", 260, 499), ("Ultralight Bivy", 90, 199)],
    "Packs": [("Trail 30L Daypack", 35, 89), ("Expedition 65L Pack", 110, 279), ("Hydration Vest", 28, 74)],
    "Footwear": [("Ridge Hiking Boot", 70, 189), ("Trail Runner", 45, 129), ("Camp Sandal", 12, 39)],
    "Apparel": [("Storm Shell Jacket", 85, 229), ("Merino Base Layer", 30, 89), ("Down Puffy", 75, 199), ("Sun Hoodie", 18, 54)],
    "Cooking": [("Titan Stove", 32, 79), ("Cook Set", 22, 59), ("Insulated Mug", 6, 24)],
    "Electronics": [("GPS Watch", 160, 349), ("Headlamp 400", 14, 44), ("Solar Charger", 40, 99)],
}
FIRST = ["Alder", "Birch", "Cedar", "Delta", "Echo", "Fjord", "Granite", "Harbor", "Iris", "Juniper",
         "Kestrel", "Lumen", "Meridian", "Nova", "Orchid", "Pine", "Quartz", "River", "Sierra", "Tundra"]
LAST = ["Outfitters", "Supply", "Adventures", "Co", "Group", "Traders", "Collective", "Partners", "Labs", "Gear"]
REPS = ["Ana Souza", "Ben Carter", "Chen Wei", "Dana Levi", "Eli Novak", "Fatima Khan",
        "Gus Berg", "Hana Sato", "Ivan Petrov", "Jada Brooks"]

SCHEMA = """
CREATE TABLE regions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    country_code TEXT NOT NULL
);
CREATE TABLE sales_reps (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    region_id INTEGER NOT NULL REFERENCES regions(id),
    hired_on DATE NOT NULL
);
CREATE TABLE sales_rep_compensation (
    rep_id INTEGER PRIMARY KEY REFERENCES sales_reps(id),
    base_salary NUMERIC NOT NULL,
    commission_rate NUMERIC NOT NULL
);
CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    segment TEXT NOT NULL CHECK (segment IN ('enterprise', 'smb', 'consumer')),
    region_id INTEGER NOT NULL REFERENCES regions(id),
    signup_date DATE NOT NULL,
    credit_limit NUMERIC
);
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_cost NUMERIC NOT NULL,
    list_price NUMERIC NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    sales_rep_id INTEGER REFERENCES sales_reps(id),
    order_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'shipped', 'delivered', 'cancelled')),
    channel TEXT NOT NULL CHECK (channel IN ('online', 'retail', 'partner')),
    shipping_cost NUMERIC NOT NULL DEFAULT 0
);
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price NUMERIC NOT NULL,
    discount_pct NUMERIC NOT NULL DEFAULT 0
);
CREATE INDEX ix_orders_date ON orders(order_date);
CREATE INDEX ix_items_order ON order_items(order_id);
"""


def create_demo_database(path: str, seed: int = 42) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    rng = random.Random(seed)
    today = date.today()
    start = today - timedelta(days=730)

    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO regions VALUES (?,?,?)", [(i + 1, n, c) for i, (n, c) in enumerate(REGIONS)])

    con.executemany(
        "INSERT INTO sales_reps VALUES (?,?,?,?)",
        [(i + 1, n, (i % len(REGIONS)) + 1, (start - timedelta(days=rng.randint(30, 1500))).isoformat())
         for i, n in enumerate(REPS)],
    )
    con.executemany(
        "INSERT INTO sales_rep_compensation VALUES (?,?,?)",
        [(i + 1, rng.randrange(55000, 120000, 1000), round(rng.uniform(0.02, 0.08), 3)) for i in range(len(REPS))],
    )

    products = []
    pid = 0
    for category, items in CATEGORIES.items():
        for name, cost, price in items:
            pid += 1
            products.append((pid, name, category, cost, price, 0 if rng.random() < 0.08 else 1))
    con.executemany("INSERT INTO products VALUES (?,?,?,?,?,?)", products)

    customers = []
    for cid in range(1, 151):
        segment = rng.choices(["enterprise", "smb", "consumer"], weights=[2, 5, 8])[0]
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}" if segment != "consumer" else f"{rng.choice(FIRST)} {chr(65 + cid % 26)}."
        customers.append((
            cid, f"{name} #{cid}", segment, rng.choices(range(1, 7), weights=[6, 2, 4, 2, 3, 1])[0],
            (start - timedelta(days=rng.randint(0, 900)) + timedelta(days=rng.randint(0, 700))).isoformat(),
            {"enterprise": 250000, "smb": 50000, "consumer": None}[segment],
        ))
    con.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)
    customer_weight = [{"enterprise": 6, "smb": 3, "consumer": 1}[c[2]] for c in customers]

    orders, items = [], []
    item_id = 0
    for oid in range(1, 4201):
        # Growth trend plus seasonality toward the most recent months.
        day_offset = int(730 * (rng.random() ** 0.8))
        order_date = start + timedelta(days=day_offset)
        if order_date.month in (11, 12) and rng.random() < 0.3:
            order_date = min(order_date + timedelta(days=rng.randint(0, 20)), today)
        age = (today - order_date).days
        if age < 5:
            status = rng.choices(["pending", "processing", "cancelled"], weights=[6, 3, 1])[0]
        elif age < 15:
            status = rng.choices(["processing", "shipped", "cancelled", "pending"], weights=[4, 5, 1, 1])[0]
        else:
            status = rng.choices(["delivered", "cancelled", "shipped"], weights=[90, 7, 3])[0]
        channel = rng.choices(["online", "retail", "partner"], weights=[5, 3, 2])[0]
        customer = rng.choices(customers, weights=customer_weight)[0]
        rep = None if channel == "online" else rng.randint(1, len(REPS))
        orders.append((oid, customer[0], rep, order_date.isoformat(), status, channel, round(rng.uniform(0, 35), 2)))
        for _ in range(rng.choices([1, 2, 3, 4, 5], weights=[30, 30, 20, 12, 8])[0]):
            item_id += 1
            product = rng.choice(products)
            qty = rng.choices([1, 2, 3, 5, 10, 25], weights=[50, 20, 12, 8, 6, 4 if customer[2] == "enterprise" else 0])[0]
            discount = rng.choice([0, 0, 0, 0.05, 0.1, 0.15]) if customer[2] != "consumer" else rng.choice([0, 0, 0.05])
            items.append((item_id, oid, product[0], qty, float(product[4]) * rng.choice([1, 1, 1, 0.95, 0.9]), discount))
    con.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", orders)
    con.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?)", items)
    con.commit()
    con.close()
    tmp.replace(target)


def demo_url(path: str) -> str:
    return f"sqlite:///{Path(path).resolve()}"
