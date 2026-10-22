"""The profile / skills part of a description (normalization/sections.py, M24)."""
from job_match.normalization.sections import profile_text

OFFER = "\n".join([
    "Quartz Santé recrute. Docker en production.",
    "",
    "Vos missions :",
    "- Gérer les clusters Kubernetes",
    "",
    "Profil recherché",
    "Bac+5, tu maîtrises Terraform.",
    "- AWS",
    "",
    "Avantages : tickets restaurant",
    "Compétences : Python, Ansible",
])


def test_only_the_profile_and_skills_sections_are_kept():
    assert profile_text(OFFER) == "Bac+5, tu maîtrises Terraform.\n- AWS\nPython, Ansible"


def test_a_heading_with_its_text_on_the_same_line_counts():
    assert profile_text("Savoir-faire : Linux, Bash\nNous offrons : un vélo") == "Linux, Bash"


def test_headings_are_matched_without_accents_or_colons():
    assert profile_text("COMPETENCES REQUISES\n- Docker") == "- Docker"
    assert profile_text("Votre profil :\nDocker") == "Docker"


def test_no_heading_means_no_profile_text():
    assert profile_text("Une équipe de huit. Kubernetes et Docker au quotidien.") == ""
    assert profile_text("") == ""
    # a bullet that starts like a heading is content, not a heading
    assert profile_text("Missions :\n- Profil des utilisateurs à documenter") == ""
