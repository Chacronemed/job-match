"""French place names → department codes.

Reference data, not configuration: France Travail returns `"NN - City"`, but Jooble and
Adzuna return bare city or region names ("Nanterre", "Île-de-France"). The location gate
needs a department code, so these tables map a name back to one.

Towns come from the official communes list (`fr_communes.tsv`, built by
`scripts/build_fr_communes.py` from geo.api.gouv.fr), loaded by `location.py`. What lives
here is the rest: regions, department names, a few business districts that are not communes,
and the foreign markers. Keys are matched after `normalize_text`, so accents, case and hyphens
do not matter.
"""

# Metropolitan regions (2016 borders) plus the overseas ones, exhaustive.
REGION_DEPARTMENTS: dict[str, tuple[str, ...]] = {
    "Île-de-France": ("75", "77", "78", "91", "92", "93", "94", "95"),
    "Centre-Val de Loire": ("18", "28", "36", "37", "41", "45"),
    "Bourgogne-Franche-Comté": ("21", "25", "39", "58", "70", "71", "89", "90"),
    "Normandie": ("14", "27", "50", "61", "76"),
    "Hauts-de-France": ("02", "59", "60", "62", "80"),
    "Grand Est": ("08", "10", "51", "52", "54", "55", "57", "67", "68", "88"),
    "Pays de la Loire": ("44", "49", "53", "72", "85"),
    "Bretagne": ("22", "29", "35", "56"),
    "Nouvelle-Aquitaine": (
        "16", "17", "19", "23", "24", "33", "40", "47", "64", "79", "86", "87",
    ),
    "Occitanie": (
        "09", "11", "12", "30", "31", "32", "34", "46", "48", "65", "66", "81", "82",
    ),
    "Auvergne-Rhône-Alpes": (
        "01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74",
    ),
    "Provence-Alpes-Côte d'Azur": ("04", "05", "06", "13", "83", "84"),
    "Corse": ("2A", "2B"),
    "Guadeloupe": ("971",),
    "Martinique": ("972",),
    "Guyane": ("973",),
    "La Réunion": ("974",),
    "Mayotte": ("976",),
}

# Department names. The multi-word ones are all here; single-word names ("Nord", "Loire",
# "Vienne") are left out on purpose: they collide with towns and with unrelated words ("Paris
# Nord"), and a town name resolves them better anyway. Essonne and Yvelines are the exception,
# job boards use them as the place.
DEPARTMENT_NAMES: dict[str, str] = {
    "Alpes-de-Haute-Provence": "04", "Hautes-Alpes": "05", "Alpes-Maritimes": "06",
    "Bouches-du-Rhône": "13", "Corse-du-Sud": "2A", "Haute-Corse": "2B", "Côte-d'Or": "21",
    "Côtes-d'Armor": "22", "Eure-et-Loir": "28", "Haute-Garonne": "31", "Ille-et-Vilaine": "35",
    "Indre-et-Loire": "37", "Loir-et-Cher": "41", "Haute-Loire": "43", "Loire-Atlantique": "44",
    "Lot-et-Garonne": "47", "Maine-et-Loire": "49", "Haute-Marne": "52",
    "Meurthe-et-Moselle": "54", "Pas-de-Calais": "62", "Puy-de-Dôme": "63",
    "Pyrénées-Atlantiques": "64", "Hautes-Pyrénées": "65", "Pyrénées-Orientales": "66",
    "Bas-Rhin": "67", "Haut-Rhin": "68", "Haute-Saône": "70", "Saône-et-Loire": "71",
    "Haute-Savoie": "74", "Seine-Maritime": "76", "Seine-et-Marne": "77", "Yvelines": "78",
    "Deux-Sèvres": "79", "Tarn-et-Garonne": "82", "Haute-Vienne": "87",
    "Territoire de Belfort": "90", "Essonne": "91", "Hauts-de-Seine": "92",
    "Seine-Saint-Denis": "93", "Val-de-Marne": "94", "Val-d'Oise": "95", "La Réunion": "974",
}

# Business districts and agglomerations that are *not* communes, so the official list cannot
# know them, yet job boards use them as the location. Short on purpose: a town belongs in the
# communes file, not here.
EXTRA_PLACES: dict[str, str] = {
    "La Défense": "92", "Paris La Défense": "92", "Nanterre-Préfecture": "92",
    "Marne-la-Vallée": "77", "Sophia Antipolis": "06", "Saint-Quentin-en-Yvelines": "78",
    "Cergy-Pontoise": "95", "La Plaine Saint-Denis": "93", "Lyon-Part-Dieu": "69",
    "Courtabœuf": "91", "Roissy CDG": "95", "Orly Aéroport": "94",
}


# Every French department and overseas code: 01-95 (Corsica is 2A/2B, never 20), the DOM
# and the overseas collectivities. Used to tell a real department prefix from France
# Travail's "99 - <COUNTRY>" abroad marker.
FRENCH_DEPARTMENTS: frozenset[str] = frozenset(
    [f"{n:02d}" for n in range(1, 96) if n != 20]
    + ["2A", "2B"]
    + [str(n) for n in range(971, 979)]     # Guadeloupe .. Saint-Martin
    + ["984", "986", "987", "988"]          # TAAF, Wallis, Polynesie, Nouvelle-Caledonie
)

# Clearly-not-France markers, matched as whole words after `normalize_text` (so they are
# written accent-free here). Deliberately short: countries plus the few foreign cities that
# actually show up in French job boards. A place that is not listed stays *unknown*, and an
# unknown location is kept, never rejected.
FOREIGN_PLACES: tuple[str, ...] = (
    "belgique", "belgium", "bruxelles", "brussels", "anvers", "liege", "wallonie", "flandre",
    "luxembourg", "suisse", "switzerland", "geneve", "lausanne", "zurich", "bale",
    "allemagne", "germany", "deutschland", "berlin", "munich", "francfort", "frankfurt",
    "espagne", "spain", "madrid", "barcelone", "barcelona", "italie", "italy", "milan",
    "rome", "turin", "royaume uni", "united kingdom", "angleterre", "england", "uk", "londres",
    "london", "irlande", "ireland", "dublin", "pays bas", "netherlands", "amsterdam",
    "rotterdam", "portugal", "lisbonne", "lisbon", "porto", "pologne", "poland", "varsovie",
    "roumanie", "bucarest", "maroc", "morocco", "casablanca", "rabat", "tunisie", "tunis",
    "algerie", "alger", "senegal", "dakar", "cote d ivoire", "abidjan", "canada", "quebec",
    "ontario", "toronto", "vancouver", "etats unis", "united states", "united states of america",
    "usa", "u s a", "washington dc", "washington d c", "new york", "san francisco", "los angeles",
    "chicago", "boston", "seattle", "austin", "denver", "atlanta", "dallas", "houston",
    "singapour", "singapore", "dubai", "emirats arabes unis", "inde", "india", "bangalore",
    "australie", "australia", "sydney", "melbourne",
    # US states: unambiguous abroad markers on a French job board.
    "alabama", "alaska", "arizona", "arkansas", "california", "californie", "colorado",
    "connecticut", "delaware", "florida", "floride", "georgia", "hawaii", "idaho", "illinois",
    "indiana", "iowa", "kansas", "kentucky", "louisiana", "louisiane", "maryland",
    "massachusetts", "michigan", "minnesota", "mississippi", "missouri", "montana", "nebraska",
    "nevada", "new hampshire", "new jersey", "new mexico", "north carolina", "north dakota",
    "ohio", "oklahoma", "oregon", "pennsylvania", "pennsylvanie", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "virginie", "washington", "west virginia", "wisconsin", "wyoming",
)

# "City, ST": the US and Canadian way of writing a location. Checked on the raw string
# (uppercase, after a comma, at the end), so "Paris, LA DEFENSE" is not Louisiana.
US_STATE_CODES: frozenset[str] = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH "
    "NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC "
    "AB BC MB NB NL NS NT NU ON PE QC SK YT".split()
)
