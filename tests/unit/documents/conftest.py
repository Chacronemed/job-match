"""A synthetic master CV and a contact sheet full of trap values. The real ones live in
private/ and are never a fixture."""
import copy

import pytest

MASTER = {
    "headline": "Ingénieur DevOps",
    "target": "CDI DevOps",
    "available_from": "2027-01-15",
    "mobility": "ouvert à la mobilité",
    "experiences": [
        {
            "id": "exp1", "employer": "Acme", "title": "DevOps", "start": "2025-01",
            "end": None, "location": "Paris",
            "bullets": [
                {"id": "exp1.b1", "text": "Migration de 12 services vers Kubernetes.",
                 "tools": ["Kubernetes", "Helm"]},
                {"id": "exp1.b2", "text": "Pipelines CI/CD GitLab, 30 merge requests par mois.",
                 "tools": ["GitLab"]},
            ],
        },
        {
            "id": "exp2", "employer": "Globex", "title": "Stagiaire", "start": "2024-05",
            "end": "2024-07", "location": "Lyon",
            "bullets": [{"id": "exp2.b1", "text": "Déploiement sur AWS.", "tools": ["AWS", "EC2"]}],
        },
    ],
    "projects": [{
        "id": "proj1", "name": "Parking",
        "bullets": [{"id": "proj1.b1", "text": "IoT et Python.", "tools": ["Python"]}],
    }],
    "skills": [{"id": "kubernetes", "label": "Kubernetes"}, {"id": "k8s", "label": "K8s"},
               {"id": "terraform", "label": "Terraform"}, {"id": "gcp", "label": "GCP"},
               {"id": "cicd", "label": "CI/CD"}, {"id": "helm", "label": "Helm"}],
    "skill_groups": [{"group": "Cloud", "items": ["AWS (EC2)", "GCP"]}],
    "education": [{"degree": "Ingénieur", "school": "ENS", "location": "Rabat",
                   "start": "2022-09", "end": "2025-06"}],
    "certifications": ["Cert A"],
    "languages": [{"name": "Français", "level": "bilingue"}],
    "extras": ["Président d'une association étudiante."],
}
CONTACT = {
    "first_name": "Jean", "last_name": "Trapmarker", "title": "Ingénieur Trapcloud",
    "email": "jean.trap@example.com", "phone": "+33 6 12 34 56 78",
    "linkedin": "linkedin.com/in/trap", "github": "github.com/trap",
    "location": "Lyon-Trapville",
}


@pytest.fixture
def master_raw():
    return copy.deepcopy(MASTER)


@pytest.fixture
def contact_raw():
    return copy.deepcopy(CONTACT)
