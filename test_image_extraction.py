"""Self-check pour l'extraction depuis une image (jpg/png) — pas d'appel API reel."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pdf_extractor as pe


def _fake_response(json_payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(json_payload))]
    return resp


def test_media_type_mapping():
    assert pe._IMAGE_MEDIA_TYPES["jpg"] == "image/jpeg"
    assert pe._IMAGE_MEDIA_TYPES["jpeg"] == "image/jpeg"
    assert pe._IMAGE_MEDIA_TYPES["png"] == "image/png"
    assert pe._IMAGE_MEDIA_TYPES["webp"] == "image/webp"
    assert pe._IMAGE_MEDIA_TYPES["gif"] == "image/gif"


def test_extract_from_image_sends_image_block_with_correct_media_type():
    payload = {
        "marque": "Rolex", "client": {"nom": "TEST"},
        "sav": {"numero": "123456", "date": "01.01.2026", "lieu": "Avignon"},
        "montre": {"modele": "SUBMARINER", "reference": "REF", "numero_serie": "SN",
                   "poids": "", "metal": "", "taille": "", "etat": []},
        "service_complet_description": "", "notes_partenaire": "",
        "interventions_necessaires": [{"description": "REVISION", "prix": 100.0}],
        "interventions_optionnelles": [], "total_ttc": 100.0, "delai": "4 semaines",
    }

    with patch("pdf_extractor.anthropic.Anthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create.return_value = _fake_response(payload)

        data = pe.extract_from_image(b"\xff\xd8\xfffakejpeg", api_key="fake-key", filename="capture_devis.png")

        # verifie que le bloc envoye a Claude est bien un "image", media_type png
        _, kwargs = instance.messages.create.call_args
        user_content = kwargs["messages"][0]["content"]
        assert user_content[0]["type"] == "image"
        assert user_content[0]["source"]["media_type"] == "image/png"

    assert data["marque"] == "Rolex"
    assert data["interventions_necessaires"][0]["prix"] == 100.0


def test_extract_from_paste_combines_text_and_images():
    payload = {
        "marque": "Fred", "client": {"nom": ""},
        "sav": {"numero": "", "date": "", "lieu": ""},
        "montre": {"modele": "", "reference": "", "numero_serie": "",
                   "poids": "", "metal": "", "taille": "", "etat": []},
        "service_complet_description": "", "notes_partenaire": "",
        "interventions_necessaires": [], "interventions_optionnelles": [],
        "total_ttc": 0.0, "delai": "",
    }
    with patch("pdf_extractor.anthropic.Anthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create.return_value = _fake_response(payload)

        data = pe.extract_from_paste(
            "Bonjour, voici le devis ci-dessous",
            [(b"imgbytes", "inline_0.png")],
            api_key="fake-key",
        )

        _, kwargs = instance.messages.create.call_args
        user_content = kwargs["messages"][0]["content"]
        assert user_content[0]["type"] == "text"
        assert user_content[1]["type"] == "image"

    # Regle metier : le mode texte/paste ne doit PAS forcer coeff_base="ht"
    # (seul le regex HT dans app.py decide, contrairement au PDF/image seuls).
    assert "coeff_base" not in data


def test_extract_from_paste_images_only_no_text():
    payload = {"marque": "Autre", "client": {"nom": ""}, "sav": {"numero": "", "date": "", "lieu": ""},
               "montre": {"modele": "", "reference": "", "numero_serie": "", "poids": "", "metal": "",
                          "taille": "", "etat": []}, "service_complet_description": "", "notes_partenaire": "",
               "interventions_necessaires": [], "interventions_optionnelles": [], "total_ttc": 0.0, "delai": ""}
    with patch("pdf_extractor.anthropic.Anthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create.return_value = _fake_response(payload)
        pe.extract_from_paste("", [(b"imgbytes", "clipboard_0.png")], api_key="fake-key")
        _, kwargs = instance.messages.create.call_args
        user_content = kwargs["messages"][0]["content"]
        assert len(user_content) == 1
        assert user_content[0]["type"] == "image"


def test_extract_from_pdf_still_forces_ht():
    payload = {"marque": "Rolex", "client": {"nom": ""}, "sav": {"numero": "", "date": "", "lieu": ""},
               "montre": {"modele": "", "reference": "", "numero_serie": "", "poids": "", "metal": "",
                          "taille": "", "etat": []}, "service_complet_description": "", "notes_partenaire": "",
               "interventions_necessaires": [], "interventions_optionnelles": [], "total_ttc": 0.0, "delai": ""}
    with patch("pdf_extractor.anthropic.Anthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create.return_value = _fake_response(payload)
        data = pe.extract_from_pdf(b"%PDF-fake", api_key="fake-key", filename="devis.pdf")
    assert data["coeff_base"] == "ht"


def test_extract_from_image_unknown_extension_falls_back_to_jpeg():
    payload = {
        "marque": "Autre", "client": {"nom": ""},
        "sav": {"numero": "", "date": "", "lieu": ""},
        "montre": {"modele": "", "reference": "", "numero_serie": "",
                   "poids": "", "metal": "", "taille": "", "etat": []},
        "service_complet_description": "", "notes_partenaire": "",
        "interventions_necessaires": [], "interventions_optionnelles": [],
        "total_ttc": 0.0, "delai": "",
    }
    with patch("pdf_extractor.anthropic.Anthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create.return_value = _fake_response(payload)
        pe.extract_from_image(b"data", api_key="fake-key", filename="screenshot")  # pas d'extension
        _, kwargs = instance.messages.create.call_args
        assert kwargs["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"


def test_html_to_text_strips_tags_and_unescapes():
    html = "<html><body><p>Bonjour&nbsp;M.&amp;nbsp;Dupont</p><br><div>Ligne 2</div></body></html>"
    text = pe._html_to_text(html)
    assert "<" not in text and ">" not in text
    assert "Bonjour" in text and "Ligne 2" in text


def test_html_to_text_empty_input():
    assert pe._html_to_text(None) == ""
    assert pe._html_to_text("") == ""


def test_extract_from_eml_falls_back_to_html_body_and_filters_small_images():
    """Simule un mail HTML-only (pas de text/plain) avec un logo minuscule + une
    image de devis substantielle en pièce jointe — reproduit le cas Hermès réel."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.image import MIMEImage

    msg = MIMEMultipart()
    msg["Subject"] = "SAV 123456"
    msg["From"] = "sav@marque.com"
    msg.attach(MIMEText("<html><body><p>DEVIS 123456 : REVISION 100 EUR HT</p></body></html>", "html"))
    msg.attach(MIMEImage(b"x" * 100, _subtype="png", name="logo_signature.png"))        # 100 octets -> filtré
    msg.attach(MIMEImage(b"y" * 5000, _subtype="jpeg", name="devis_capture.jpg"))       # 5000 octets -> gardé
    eml_bytes = msg.as_bytes()

    payload = {
        "marque": "Autre", "client": {"nom": ""}, "sav": {"numero": "123456", "date": "", "lieu": ""},
        "montre": {"modele": "", "reference": "", "numero_serie": "", "poids": "", "metal": "",
                   "taille": "", "etat": []}, "service_complet_description": "", "notes_partenaire": "",
        "interventions_necessaires": [{"description": "REVISION", "prix": 100.0}],
        "interventions_optionnelles": [], "total_ttc": 100.0, "delai": "",
    }
    with patch("pdf_extractor.anthropic.Anthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create.return_value = _fake_response(payload)
        data, source_kind, _ = pe.extract_from_eml(eml_bytes, api_key="fake-key", filename="mail.eml")
        _, kwargs = instance.messages.create.call_args
        content = kwargs["messages"][0]["content"]

    assert source_kind == "text"
    assert content[0]["type"] == "text" and "DEVIS 123456" in content[0]["text"]
    # une seule image (la petite a ete filtree)
    image_blocks = [b for b in content if b["type"] == "image"]
    assert len(image_blocks) == 1
    assert data["interventions_necessaires"][0]["prix"] == 100.0


if __name__ == "__main__":
    test_media_type_mapping()
    test_extract_from_image_sends_image_block_with_correct_media_type()
    test_extract_from_paste_combines_text_and_images()
    test_extract_from_paste_images_only_no_text()
    test_extract_from_pdf_still_forces_ht()
    test_extract_from_image_unknown_extension_falls_back_to_jpeg()
    test_html_to_text_strips_tags_and_unescapes()
    test_html_to_text_empty_input()
    test_extract_from_eml_falls_back_to_html_body_and_filters_small_images()
    print("OK - extraction image + paste + eml/msg html fallback")
