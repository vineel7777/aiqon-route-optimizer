"""Central configuration: the synthetic port network, shipment profiles and model constants.

Everything that is an *assumption* lives here so it can be audited and changed in one place.
"""

# --------------------------------------------------------------------------------------
# Network.  code: (name, role, congestion 0-1, dwell days if used as transshipment hub,
#                  handling cost USD per TEU if used as transshipment hub)
# --------------------------------------------------------------------------------------
NODES = {
    # origins (Indian gateway ports)
    "CHE": ("Chennai", "origin", 0.35, 0, 0),
    "NSA": ("Nhava Sheva", "origin", 0.45, 0, 0),
    "MUN": ("Mundra", "origin", 0.30, 0, 0),
    # transshipment hubs
    "CMB": ("Colombo", "hub", 0.55, 2.0, 90),
    "SIN": ("Singapore", "hub", 0.60, 2.0, 110),
    "JEA": ("Jebel Ali", "hub", 0.40, 1.5, 100),
    "SLL": ("Salalah", "hub", 0.25, 1.5, 70),
    "PSD": ("Port Said", "hub", 0.50, 2.0, 80),
    "PIR": ("Piraeus", "hub", 0.40, 1.5, 85),
    "CPT": ("Cape Town", "hub", 0.35, 2.0, 120),
    "PKG": ("Port Klang", "hub", 0.50, 1.5, 80),
    "HKG": ("Hong Kong", "hub", 0.55, 2.0, 100),
    # destinations
    "RTM": ("Rotterdam", "dest", 0.55, 0, 0),
    "HAM": ("Hamburg", "dest", 0.45, 0, 0),
    "FXT": ("Felixstowe", "dest", 0.50, 0, 0),
    "NYC": ("New York", "dest", 0.55, 0, 0),
    "LAX": ("Los Angeles", "dest", 0.65, 0, 0),
}
ORIGINS = [k for k, v in NODES.items() if v[1] == "origin"]
DESTS = [k for k, v in NODES.items() if v[1] == "dest"]
HUBS = [k for k, v in NODES.items() if v[1] == "hub"]

# Sea lanes (undirected): (a, b, nominal_days, USD per TEU, base P(delay), geopolitical risk 0-1)
# Red Sea / Gulf of Aden lanes (->PSD) carry high geopolitical risk; Cape lanes are slower but calmer.
SEA_EDGES = [
    ("CHE", "CMB", 2, 300, 0.08, 0.05), ("NSA", "CMB", 4, 380, 0.08, 0.05), ("MUN", "CMB", 5, 410, 0.08, 0.05),
    ("CHE", "SIN", 5, 520, 0.10, 0.10), ("NSA", "SIN", 8, 600, 0.10, 0.10), ("MUN", "SIN", 9, 640, 0.10, 0.10),
    ("NSA", "JEA", 3, 360, 0.08, 0.20), ("MUN", "JEA", 2, 300, 0.08, 0.20),
    ("NSA", "SLL", 4, 400, 0.08, 0.10), ("MUN", "SLL", 4, 410, 0.08, 0.10),
    ("CMB", "SIN", 3, 330, 0.08, 0.10), ("CMB", "JEA", 5, 420, 0.08, 0.20), ("CMB", "SLL", 4, 360, 0.08, 0.08),
    ("CMB", "PSD", 11, 650, 0.12, 0.55), ("JEA", "PSD", 8, 520, 0.12, 0.60),
    ("SLL", "PSD", 6, 480, 0.12, 0.60), ("SIN", "PSD", 13, 780, 0.12, 0.55),
    ("PSD", "PIR", 3, 200, 0.06, 0.15),
    ("PSD", "RTM", 7, 400, 0.08, 0.15), ("PSD", "HAM", 8, 430, 0.08, 0.15), ("PSD", "FXT", 8, 420, 0.08, 0.15),
    ("PSD", "NYC", 13, 700, 0.10, 0.12),
    ("PIR", "RTM", 8, 380, 0.08, 0.08), ("PIR", "HAM", 9, 400, 0.08, 0.08), ("PIR", "FXT", 8, 400, 0.08, 0.08),
    ("PIR", "NYC", 12, 650, 0.10, 0.08),
    ("SLL", "CPT", 9, 600, 0.10, 0.12), ("JEA", "CPT", 11, 700, 0.10, 0.12),
    ("SIN", "CPT", 12, 760, 0.10, 0.08), ("CMB", "CPT", 11, 700, 0.10, 0.10),
    ("CPT", "RTM", 14, 650, 0.10, 0.06), ("CPT", "HAM", 15, 680, 0.10, 0.06),
    ("CPT", "FXT", 13, 640, 0.10, 0.06), ("CPT", "NYC", 16, 800, 0.10, 0.05),
    ("SIN", "LAX", 18, 1100, 0.10, 0.08),
    # Southeast-Asia / trans-Pacific alternatives
    ("CHE", "PKG", 4, 450, 0.09, 0.08), ("NSA", "PKG", 7, 550, 0.09, 0.08), ("MUN", "PKG", 8, 600, 0.09, 0.08),
    ("CMB", "PKG", 3, 310, 0.08, 0.08), ("SIN", "PKG", 1, 120, 0.06, 0.08), ("PKG", "HKG", 4, 250, 0.08, 0.10),
    ("SIN", "HKG", 4, 260, 0.08, 0.10), ("HKG", "LAX", 14, 1050, 0.10, 0.10), ("PKG", "LAX", 19, 1150, 0.10, 0.08),
]
# Direct air options (origin -> destination): (days, USD per TEU-equivalent)
AIR = {"EU": (2.5, 8500), "US": (3.0, 11000)}
AIR_BASE_P, AIR_GEO = 0.06, 0.02
US_DESTS = {"NYC", "LAX"}

# --------------------------------------------------------------------------------------
# Delay model (shared by data generation, scoring and evaluation)
# --------------------------------------------------------------------------------------
P_CONG_COEF, P_GEO_COEF = 0.22, 0.12          # leg P(delay) = base + 0.22*congestion + 0.12*geo
MU_BASE, MU_CONG, MU_GEO = 1.2, 4.0, 3.0       # mean delay days when a delay occurs (sea)
AIR_MU_BASE, AIR_MU_CONG = 0.5, 1.0
DELAY_SIGMA = 0.6                               # lognormal shape of delay duration
SHOCK_P_PER_GEO = 0.25                          # P(disruption/reroute shock on a leg) = 0.25 * geo (stressed Red Sea scenario)
SHOCK_DAYS = (7.0, 14.0)                        # uniform reroute delay if shock occurs

# Estimation noise (what the planner *sees* versus ground truth)
EST_NOISE_P, EST_NOISE_MU, EST_NOISE_INDEX = 0.25, 0.20, 0.05

# --------------------------------------------------------------------------------------
# Shipment profiles -> what "optimal" means for this shipment
# weights over normalized criteria (lower is better); min_on_time = chance constraint
# --------------------------------------------------------------------------------------
CRITERIA = ["cost", "time", "spread", "exposure"]
PROFILES = {
    "balanced":       dict(cost=0.35, time=0.25, spread=0.20, exposure=0.20, min_on_time=0.70),
    "urgent":         dict(cost=0.15, time=0.50, spread=0.25, exposure=0.10, min_on_time=0.85),
    "cost_sensitive": dict(cost=0.60, time=0.15, spread=0.15, exposure=0.10, min_on_time=0.60),
    "high_value":     dict(cost=0.20, time=0.15, spread=0.30, exposure=0.35, min_on_time=0.85),
}
# Normalisation floors: min-max range is never allowed to be tiny, so near-identical routes
# are not artificially stretched to look very different.  (relative to min value / absolute)
NORM_FLOOR = dict(cost=0.10, time=0.10, spread=1.0, exposure=0.05)

# Cargo types: share, value USD/TEU, delay cost USD/day/TEU, default profile, air allowed
CARGO = {
    "standard":    dict(share=0.35, value=25_000,  delay_cost=120, profile="balanced",       air=True),
    "commodity":   dict(share=0.15, value=10_000,  delay_cost=40,  profile="cost_sensitive", air=False),
    "perishable":  dict(share=0.20, value=40_000,  delay_cost=600, profile="urgent",         air=True),
    "electronics": dict(share=0.17, value=150_000, delay_cost=350, profile="high_value",     air=True),
    "pharma":      dict(share=0.13, value=300_000, delay_cost=500, profile="high_value",     air=True),
}
HOLDING_RATE_ANNUAL = 0.15      # evaluation only: capital cost of cargo in transit
LATE_FEE_MULT = 3.0             # evaluation only: contractual lateness = 3x delay cost per day late

N_SHIPMENTS = 35
SEED = 42
