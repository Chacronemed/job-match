"""Title families (scoring/title.py, M24): the title says what the job is."""
from pathlib import Path

import pytest

from job_match.config.loader import load_settings
from job_match.config.schema import TitleRelevanceConfig
from job_match.scoring.title import CORE, NEAR, OFF_DOMAIN, OTHER, is_off_domain, title_family

CFG = TitleRelevanceConfig(
    core=["devops", "sre", "cloud", "infra"],
    near=["administrateur système", "exploitation informatique"],
    off_domain=["recrutement", "mécanique", "embarqué"],
    core_points=20, near_points=10, other_points=-15,
)
REAL = load_settings(Path("config/settings.yaml")).title_relevance


@pytest.mark.parametrize("title, family, points", [
    ("Ingénieur DevOps H/F", CORE, 20),
    ("SRE confirmé", CORE, 20),
    ("Ingénieur Infrastructure", CORE, 20),                      # prefix: infra -> Infrastructure
    ("Administrateur systèmes Linux", NEAR, 10),
    ("Technicien d'exploitation informatique", NEAR, 10),
    ("Responsable d'exploitation", OTHER, -15),                  # exploitation alone is not IT
    ("Chef de projet", OTHER, -15),
    ("Consultant en recrutement", OFF_DOMAIN, 0),
    ("Ingénieur mécanique", OFF_DOMAIN, 0),
])
def test_each_family_and_its_points(title, family, points):
    got = title_family(title, CFG)
    assert (got.family, got.points) == (family, points)


def test_a_core_term_protects_from_off_domain_and_off_domain_beats_near():
    assert title_family("Ingénieur DevOps recrutement interne", CFG).family == CORE
    # near and off-domain in one title: the other trade wins
    assert title_family("Administrateur système embarqué", CFG).family == OFF_DOMAIN


def test_matching_ignores_accents_and_case_and_names_the_term():
    got = title_family("INGENIEUR MECANIQUE DES FLUIDES", CFG)
    assert got.family == OFF_DOMAIN and got.term == "mécanique"
    assert title_family("Cloud architect", CFG).term == "cloud"


def test_empty_core_turns_the_feature_off():
    off = TitleRelevanceConfig(off_domain=["recrutement"])
    assert not off.enabled
    assert not is_off_domain("Consultant en recrutement", off)
    assert is_off_domain("Consultant en recrutement", CFG)


@pytest.mark.parametrize("title", [
    "Consultant en recrutement IT H/F",
    "Ingénieur-e moyens d'essais - mécanique des fluides F/H",
    "Ingénieur hardware",
    "Data manager",
    "Ingénieur banc de test d'intégration optronique en défense",
    "Responsable d'exploitation de site hôtelier et touristique",
])
def test_the_real_lists_veto_the_off_topic_titles_seen_in_tri(title):
    assert title_family(title, REAL).family == OFF_DOMAIN


@pytest.mark.parametrize("title", [
    "Ingénieur DevOps", "DevSecOps", "Ingénieur Cloud AWS", "Platform Engineer",
    "Site Reliability Engineer", "Ingénieur Infrastructure & Kubernetes",
])
def test_the_real_lists_put_devops_titles_in_core(title):
    assert title_family(title, REAL).family == CORE


@pytest.mark.parametrize("title", [
    "Ingénieur de production informatique", "SysOps Run / Ingénieur Production & Exploitation",
    "Administrateur systèmes et réseaux",
])
def test_the_real_lists_keep_it_operations_titles_near(title):
    assert title_family(title, REAL).family == NEAR


# ---------- roles that cancel the core protection; sectors vs trades ----------

OVR = TitleRelevanceConfig(
    core=["devops", "cloud", "infra", "aws"],
    near=["data engineer", "sauvegarde", "inter-applicatif"],
    off_domain=["data analyst", "mécanique"],
    off_domain_sectors=["marketing", "transport", "restauration", "logistique"],
    core_overrides=["commercial", "commerciale", "sales", "ingénieur d'affaires",
                    "business developer", "product owner", "chef de projet", "account manager",
                    "recruteur"],
    core_points=20, near_points=10, other_points=-15,
)


@pytest.mark.parametrize("title, role", [
    ("Ingénieur commercial Cloud", "commercial"),
    ("Ingénieure commerciale Cloud", "commerciale"),
    ("Sales Engineer DevOps", "sales"),
    ("Ingénieur d'affaires Cloud & Infra", "ingénieur d'affaires"),
    ("Business Developer Cloud", "business developer"),
    ("Product Owner Cloud", "product owner"),
    ("Chef de projet infrastructure", "chef de projet"),
    ("Account Manager AWS", "account manager"),
    ("Recruteur DevOps", "recruteur"),
])
def test_a_role_next_to_a_core_term_makes_the_title_other_never_vetoed(title, role):
    got = title_family(title, OVR)
    assert (got.family, got.term, got.points) == (OTHER, role, -15)
    assert not is_off_domain(title, OVR)


def test_overrides_are_whole_words_so_salesforce_is_not_sales():
    assert title_family("Ingénieur DevOps Salesforce", OVR).family == CORE


def test_a_trade_beats_a_near_term_but_a_near_term_beats_a_sector():
    assert title_family("Data Analyst / Data Engineer", OVR).family == OFF_DOMAIN
    assert title_family("Data Engineer - customer data / marketing", OVR).family == NEAR
    assert title_family("Ingénieur sauvegarde et restauration", OVR).family == NEAR
    secure = "Spécialiste échanges inter-applicatifs (Secure Transport)"
    assert title_family(secure, OVR).family == NEAR


def test_a_sector_word_alone_is_off_domain():
    for title in ("Technicien logistique", "Agent de restauration", "Chargé marketing digital"):
        assert title_family(title, OVR).family == OFF_DOMAIN, title
    assert is_off_domain("Technicien logistique", OVR)


@pytest.mark.parametrize("title, family", [
    ("Spécialiste échanges inter-applicatifs (Secure Transport) - Freelance (H/F)", NEAR),
    ("DATA ENGINEER FOR CUSTOMER DATA MANAGEMENT / MARKETING - Freelance (H/F)", NEAR),
    ("Ingénieur(e) commercial(e) IT (H/F)", OFF_DOMAIN),        # no core term: still vetoed
    ("Ingénieur commercial Cloud (H/F)", OTHER),
    ("Ingénieur DevOps Salesforce (H/F)", CORE),
])
def test_the_false_negatives_found_on_the_prod_copy_with_the_real_lists(title, family):
    assert title_family(title, REAL).family == family
