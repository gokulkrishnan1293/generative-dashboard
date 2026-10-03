"""A reviewed metadata wrapper for the demo database, so dashboard generation can be tested
without first completing the onboarding review by hand."""

from ..schemas import MetadataDoc

TABLES = {
    "regions": ("Sales regions used to group customers and reps.", "One sales region.", {
        "id": ("Region identifier.", "identifier", None, {}),
        "name": ("Region name, e.g. North America.", "dimension", None, {}),
        "country_code": ("ISO country code of the region's headquarters.", "dimension", None, {}),
    }),
    "sales_reps": ("Sales representatives who handle retail and partner orders.", "One sales representative.", {
        "id": ("Sales rep identifier.", "identifier", None, {}),
        "full_name": ("Rep's full name.", "dimension", None, {}),
        "region_id": ("Region the rep covers.", "identifier", None, {}),
        "hired_on": ("Date the rep was hired.", "time", None, {}),
    }),
    "sales_rep_compensation": ("Confidential compensation terms for sales reps.", "Compensation terms of one rep.", {
        "rep_id": ("Sales rep identifier.", "identifier", None, {}),
        "base_salary": ("Annual base salary.", "measure", "USD", {}),
        "commission_rate": ("Commission as a fraction of revenue.", "measure", "fraction", {}),
    }),
    "customers": ("Customers who place orders.", "One customer account.", {
        "id": ("Customer identifier.", "identifier", None, {}),
        "name": ("Customer display name.", "dimension", None, {}),
        "segment": ("Customer segment.", "dimension", None, {
            "enterprise": "Business with 500+ employees", "smb": "Small or medium business", "consumer": "Individual consumer"}),
        "region_id": ("Customer's sales region.", "identifier", None, {}),
        "signup_date": ("Date the customer account was created.", "time", None, {}),
        "credit_limit": ("Approved credit limit; empty for consumers.", "measure", "USD", {}),
    }),
    "products": ("Product catalog.", "One product (SKU).", {
        "id": ("Product identifier.", "identifier", None, {}),
        "name": ("Product name.", "dimension", None, {}),
        "category": ("Product category, e.g. Tents, Footwear.", "dimension", None, {}),
        "unit_cost": ("Cost to the company per unit.", "measure", "USD", {}),
        "list_price": ("Standard selling price per unit.", "measure", "USD", {}),
        "is_active": ("1 if the product is currently sold.", "flag", None, {"1": "Active", "0": "Discontinued"}),
    }),
    "orders": ("Customer orders (order headers).", "One order placed by a customer.", {
        "id": ("Order identifier.", "identifier", None, {}),
        "customer_id": ("Customer who placed the order.", "identifier", None, {}),
        "sales_rep_id": ("Rep who handled the order; empty for online orders.", "identifier", None, {}),
        "order_date": ("Date the order was placed.", "time", None, {}),
        "status": ("Fulfilment status of the order.", "dimension", None, {
            "pending": "Placed, awaiting payment confirmation", "processing": "Paid, being picked and packed",
            "shipped": "Handed to carrier", "delivered": "Received by customer",
            "cancelled": "Cancelled; excluded from revenue reporting"}),
        "channel": ("Sales channel.", "dimension", None, {
            "online": "Web store", "retail": "Retail stores", "partner": "Partner resellers"}),
        "shipping_cost": ("Shipping charged on the order.", "measure", "USD", {}),
    }),
    "order_items": ("Order lines.", "One product line within an order.", {
        "id": ("Order line identifier.", "identifier", None, {}),
        "order_id": ("Order this line belongs to.", "identifier", None, {}),
        "product_id": ("Product sold on this line.", "identifier", None, {}),
        "quantity": ("Units sold.", "measure", "units", {}),
        "unit_price": ("Price actually charged per unit before discount.", "measure", "USD", {}),
        "discount_pct": ("Discount as a fraction (0.1 = 10%).", "measure", "fraction", {}),
    }),
}

LINE_REVENUE = {"op": "mul", "args": [
    {"op": "mul", "args": [{"column": "order_items.quantity"}, {"column": "order_items.unit_price"}]},
    {"op": "sub", "args": [{"literal": 1}, {"column": "order_items.discount_pct"}]},
]}

METRICS = [
    {"name": "revenue", "label": "Revenue", "agg": "sum", "format": "currency", "expr": LINE_REVENUE,
     "description": "quantity × unit_price × (1 − discount). Exclude cancelled orders when reporting revenue."},
    {"name": "gross_margin", "label": "Gross margin", "agg": "sum", "format": "currency",
     "expr": {"op": "sub", "args": [LINE_REVENUE, {"op": "mul", "args": [
         {"column": "order_items.quantity"}, {"column": "products.unit_cost"}]}]},
     "description": "Revenue minus quantity × product unit cost."},
    {"name": "units_sold", "label": "Units sold", "agg": "sum", "format": "integer",
     "expr": {"column": "order_items.quantity"}, "description": "Total units on order lines."},
    {"name": "order_count", "label": "Orders", "agg": "count_distinct", "format": "integer",
     "expr": {"column": "orders.id"}, "description": "Number of distinct orders."},
    {"name": "customer_count", "label": "Customers", "agg": "count_distinct", "format": "integer",
     "expr": {"column": "customers.id"}, "description": "Number of distinct customers."},
]


def apply_demo_metadata(doc: MetadataDoc) -> MetadataDoc:
    for t in doc.tables:
        spec = TABLES.get(t.name)
        if not spec:
            continue
        t.description, t.row_meaning, cols = spec
        t.status, t.confidence, t.ambiguities = "approved", 1.0, []
        t.restricted = t.name == "sales_rep_compensation"
        for c in t.columns:
            if c.name not in cols:
                continue
            c.description, c.semantic_type, c.unit, c.coded_values = cols[c.name]
            c.status, c.confidence, c.ambiguities, c.schema_change = "approved", 1.0, [], None
    for r in doc.relationships:
        r.status, r.confidence, r.ambiguities = "approved", 1.0, []
        r.description = r.description or f"Each {r.from_table} row references one {r.to_table} row."
    from ..schemas import MetricMeta

    existing = {m.name for m in doc.metrics}
    for m in METRICS:
        if m["name"] not in existing:
            doc.metrics.append(MetricMeta.model_validate({**m, "status": "approved", "confidence": 1.0}))
    return doc
