"""French place names → department codes.

Reference data, not configuration: France Travail returns `"NN - City"`, but Jooble and
Adzuna return bare city or region names ("Nanterre", "Île-de-France"). The location gate
needs a department code to compare against `ft_search.departments`, so these tables map a
name back to one.

Deliberately incomplete. A name that is not here resolves to no department, and the gate
keeps the job rather than rejecting it (see `departments_for`). Entries exist for two
reasons: so suburbs of the departments we query are *accepted* (the IdF ring, Lyon,
Toulouse, Lille, Bordeaux, Rennes, Sophia Antipolis), and so clearly out-of-area cities
can be *rejected* instead of silently kept.

Keys are matched after `normalize_text`, so accents, case and hyphens do not matter here.
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

# Department names, only for the ones worth naming: single-word names ("Nord", "Rhône")
# are left out on purpose — they appear inside unrelated strings like "Paris Nord".
DEPARTMENT_NAMES: dict[str, str] = {
    "Hauts-de-Seine": "92",
    "Seine-Saint-Denis": "93",
    "Val-de-Marne": "94",
    "Val-d'Oise": "95",
    "Seine-et-Marne": "77",
    "Haute-Garonne": "31",
    "Ille-et-Vilaine": "35",
    "Alpes-Maritimes": "06",
    "Loire-Atlantique": "44",
    "Bas-Rhin": "67",
    "Haut-Rhin": "68",
    "Bouches-du-Rhône": "13",
    "Pas-de-Calais": "62",
    "Haute-Savoie": "74",
    "Puy-de-Dôme": "63",
}

# Cities. Dense for the departments we query, a prefecture-level sample elsewhere.
CITY_DEPARTMENT: dict[str, str] = {
    # 75
    "Paris": "75",
    # 92 — Hauts-de-Seine
    "Nanterre": "92", "Boulogne-Billancourt": "92", "Courbevoie": "92", "Puteaux": "92",
    "La Défense": "92", "Levallois-Perret": "92", "Issy-les-Moulineaux": "92",
    "Clichy": "92", "Asnières-sur-Seine": "92", "Colombes": "92", "Gennevilliers": "92",
    "Rueil-Malmaison": "92", "Neuilly-sur-Seine": "92", "Montrouge": "92", "Antony": "92",
    "Clamart": "92", "Suresnes": "92", "Châtillon": "92", "Malakoff": "92", "Vanves": "92",
    "Meudon": "92", "Sèvres": "92", "Bagneux": "92", "Garches": "92", "Nanterre-Préfecture": "92",
    # 93 — Seine-Saint-Denis
    "Saint-Denis": "93", "Montreuil": "93", "Aubervilliers": "93", "Pantin": "93",
    "Bobigny": "93", "Noisy-le-Grand": "93", "Rosny-sous-Bois": "93", "Bagnolet": "93",
    "Saint-Ouen": "93", "Romainville": "93", "Villepinte": "93", "Aulnay-sous-Bois": "93",
    "Le Bourget": "93", "La Plaine Saint-Denis": "93", "Épinay-sur-Seine": "93",
    # 94 — Val-de-Marne
    "Créteil": "94", "Vitry-sur-Seine": "94", "Ivry-sur-Seine": "94", "Villejuif": "94",
    "Charenton-le-Pont": "94", "Saint-Maur-des-Fossés": "94", "Fontenay-sous-Bois": "94",
    "Vincennes": "94", "Alfortville": "94", "Rungis": "94", "Orly": "94",
    "Maisons-Alfort": "94", "Choisy-le-Roi": "94", "Thiais": "94", "Arcueil": "94",
    "Cachan": "94", "Nogent-sur-Marne": "94",
    # 91 — Essonne
    "Évry": "91", "Évry-Courcouronnes": "91", "Massy": "91", "Palaiseau": "91",
    "Saclay": "91", "Orsay": "91", "Les Ulis": "91", "Corbeil-Essonnes": "91",
    "Villebon-sur-Yvette": "91", "Bondoufle": "91", "Courtabœuf": "91", "Longjumeau": "91",
    "Essonne": "91",
    # 78 — Yvelines
    "Versailles": "78", "Saint-Quentin-en-Yvelines": "78", "Montigny-le-Bretonneux": "78",
    "Guyancourt": "78", "Vélizy-Villacoublay": "78", "Poissy": "78", "Mantes-la-Jolie": "78",
    "Les Mureaux": "78", "Rambouillet": "78", "Trappes": "78", "Plaisir": "78",
    "Élancourt": "78", "Yvelines": "78",
    # 77 — Seine-et-Marne
    "Melun": "77", "Chessy": "77", "Marne-la-Vallée": "77", "Serris": "77", "Torcy": "77",
    "Meaux": "77", "Fontainebleau": "77", "Lognes": "77", "Noisiel": "77",
    "Bussy-Saint-Georges": "77", "Croissy-Beaubourg": "77", "Chelles": "77",
    # 95 — Val-d'Oise
    "Cergy": "95", "Cergy-Pontoise": "95", "Pontoise": "95", "Roissy-en-France": "95",
    "Argenteuil": "95", "Sarcelles": "95", "Osny": "95", "Gonesse": "95",
    "Saint-Ouen-l'Aumône": "95", "Villiers-le-Bel": "95", "Eaubonne": "95",
    # 69 — Rhône / Lyon
    "Lyon": "69", "Villeurbanne": "69", "Vénissieux": "69", "Écully": "69", "Bron": "69",
    "Dardilly": "69", "Limonest": "69", "Oullins": "69", "Saint-Priest": "69",
    "Caluire-et-Cuire": "69", "Rillieux-la-Pape": "69", "Lyon-Part-Dieu": "69",
    # 31 — Toulouse
    "Toulouse": "31", "Blagnac": "31", "Labège": "31", "Colomiers": "31", "Balma": "31",
    "Ramonville-Saint-Agne": "31", "Tournefeuille": "31", "Castanet-Tolosan": "31",
    # 59 — Lille
    "Lille": "59", "Villeneuve-d'Ascq": "59", "Roubaix": "59", "Tourcoing": "59",
    "Marcq-en-Barœul": "59", "Valenciennes": "59", "Douai": "59", "Dunkerque": "59",
    "Seclin": "59", "Lesquin": "59", "Wasquehal": "59",
    # 33 — Bordeaux
    "Bordeaux": "33", "Mérignac": "33", "Pessac": "33", "Talence": "33", "Bègles": "33",
    "Le Haillan": "33", "Bruges": "33", "Gradignan": "33", "Artigues-près-Bordeaux": "33",
    "Canéjan": "33",
    # 35 — Rennes
    "Rennes": "35", "Cesson-Sévigné": "35", "Saint-Grégoire": "35", "Bruz": "35",
    "Chantepie": "35", "Saint-Malo": "35", "Pacé": "35",
    # 06 — Alpes-Maritimes
    "Nice": "06", "Sophia Antipolis": "06", "Antibes": "06", "Cannes": "06",
    "Valbonne": "06", "Mougins": "06", "Biot": "06", "Grasse": "06",
    "Mandelieu-la-Napoule": "06",
    # Elsewhere — enough to reject an out-of-area city instead of keeping it
    "Marseille": "13", "Aix-en-Provence": "13", "Aubagne": "13", "Vitrolles": "13",
    "Nantes": "44", "Saint-Herblain": "44", "Saint-Nazaire": "44", "Carquefou": "44",
    "Strasbourg": "67", "Illkirch-Graffenstaden": "67", "Schiltigheim": "67",
    "Montpellier": "34", "Béziers": "34",
    "Grenoble": "38", "Échirolles": "38", "Meylan": "38",
    "Saint-Étienne": "42", "Rouen": "76", "Le Havre": "76", "Caen": "14", "Dijon": "21",
    "Clermont-Ferrand": "63", "Angers": "49", "Le Mans": "72", "Tours": "37",
    "Orléans": "45", "Reims": "51", "Nancy": "54", "Metz": "57", "Mulhouse": "68",
    "Brest": "29", "Quimper": "29", "Lorient": "56", "Vannes": "56", "Saint-Brieuc": "22",
    "Pau": "64", "Bayonne": "64", "Anglet": "64", "La Rochelle": "17", "Poitiers": "86",
    "Limoges": "87", "Besançon": "25", "Perpignan": "66", "Nîmes": "30", "Avignon": "84",
    "Toulon": "83", "Annecy": "74", "Chambéry": "73", "Amiens": "80", "Arras": "62",
    "Lens": "62", "Calais": "62", "Boulogne-sur-Mer": "62", "Compiègne": "60",
    "Beauvais": "60", "Évreux": "27", "Cherbourg": "50", "Chalon-sur-Saône": "71",
    "Valence": "26", "Carcassonne": "11", "Tarbes": "65", "Montauban": "82", "Albi": "81",
    "Auch": "32", "Cahors": "46", "Rodez": "12", "Troyes": "10", "Châlons-en-Champagne": "51",
    "Bourges": "18", "Chartres": "28", "Blois": "41", "Niort": "79", "Angoulême": "16",
    "Périgueux": "24", "Agen": "47", "Mont-de-Marsan": "40", "Bastia": "2B", "Ajaccio": "2A",
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
    "rome", "turin", "royaume uni", "united kingdom", "angleterre", "londres", "london",
    "irlande", "ireland", "dublin", "pays bas", "netherlands", "amsterdam", "rotterdam",
    "portugal", "lisbonne", "lisbon", "porto", "pologne", "poland", "varsovie",
    "roumanie", "bucarest", "maroc", "morocco", "casablanca", "rabat", "tunisie", "tunis",
    "algerie", "alger", "senegal", "dakar", "cote d ivoire", "abidjan", "canada", "quebec",
    "montreal", "etats unis", "united states", "new york", "san francisco", "londres uk",
    "singapour", "singapore", "dubai", "emirats arabes unis", "inde", "india", "bangalore",
)
