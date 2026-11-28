"""Filtre couche 1, liste blanche large E (figé 27.11.2026). passe(row) -> bool sur une ligne du CSV population-tf.
E = cours 8C/9C ∪ domaine bger assurances sociales (legal_area, sinon titre) ∪ matière UV/IV/MV
    ∪ mention Suva/CNA/INSAI/LAA/assurance-accidents dans le texte ∪ titre assurance/responsabilité/indemnités journalières.
Indice de tri, jamais un label."""
import re
SOC_AREA = re.compile(r"(unfall|accident|infortun|invalid|militär|militaire|militare|alters|vieillesse|vecchiaia|"
                      r"ergänzung|complément|complementar|vorsorge|prévoyance|previdenza|arbeitslos|chômage|disoccup|"
                      r"krankenvers|maladie|malatti|erwerbsersatz|erwerbersatz|perte de gain|perdita di guadagno|familienzulage|"
                      r"allocation familiale|soziale sicherheit|sécurité sociale|sicurezza sociale)", re.I)
TITLE_KW = re.compile(r"(unfall|accident|infortun|invalid|taggeld|indemnit|haftpflicht|responsabilit|regress|recours|"
                      r"versicherung|assurance|assicurazione|rente|vorsorge|prévoyance|integrität|atteinte à l'intégrité|"
                      r"suva|cna|insai|uvg|laa|ivg|lai|atsg|lpga|mvg|lam)", re.I)
TXT = ("txt_suva", "txt_cna", "txt_insai", "txt_loi_laa", "txt_assurance_accidents")


def passe(r):
    la, ti = r.get("legal_area") or "", r.get("title") or ""
    return (r["prefixe"] in ("8C", "9C") or bool(SOC_AREA.search(la)) or (not la and bool(SOC_AREA.search(ti)))
            or r["matiere"] in ("UV", "IV", "MV") or any(r.get(t) == "true" for t in TXT) or bool(TITLE_KW.search(ti)))
