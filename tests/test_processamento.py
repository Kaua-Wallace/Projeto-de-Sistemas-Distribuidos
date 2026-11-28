
import io

from fastapi.testclient import TestClient
from PIL import Image

from processing_service import main as processamento
from processing_service.main import app

client = TestClient(app)

def png():
    b = io.BytesIO()
    Image.new("RGB", (800, 600), "blue").save(b, "PNG")
    return b.getvalue()

def imagem_em(formato: str) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (200, 100), "red").save(b, formato)
    return b.getvalue()

def miniatura_de(dados: bytes, mime: str) -> Image.Image:
    r = client.post("/internal/thumbnail", files={"file": ("a", dados, mime)})
    assert r.status_code == 200
    return Image.open(io.BytesIO(r.content))

def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"

def test_gera_miniatura():
    r = client.post("/internal/thumbnail", files={"file": ("a.png", png(), "image/png")})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert max(Image.open(io.BytesIO(r.content)).size) <= 256

def test_tipo_invalido():
    r = client.post("/internal/thumbnail", files={"file": ("a.txt", b"oi", "text/plain")})
    assert r.status_code == 415

def test_arquivo_vazio():
    r = client.post("/internal/thumbnail", files={"file": ("a.png", b"", "image/png")})
    assert r.status_code == 400

def test_imagem_corrompida():
    arq = {"file": ("a.png", b"nao-e-png", "image/png")}
    r = client.post("/internal/thumbnail", files=arq)
    assert r.status_code == 422

def test_sem_arquivo():
    assert client.post("/internal/thumbnail").status_code == 422

def test_formatos_validos_geram_miniatura():
    casos = [
        ("PNG", "image/png"),
        ("JPEG", "image/jpeg"),
        ("GIF", "image/gif"),
        ("WEBP", "image/webp"),
    ]
    for formato, mime in casos:
        r = client.post(
            "/internal/thumbnail",
            files={"file": ("a", imagem_em(formato), mime)},
        )
        assert r.status_code == 200, formato
        assert r.headers["content-type"] == "image/jpeg"

def test_pdf_declarado_como_png_422():
    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    r = client.post("/internal/thumbnail", files={"file": ("a.png", pdf, "image/png")})
    assert r.status_code == 422

def test_png_truncado_422():
    r = client.post(
        "/internal/thumbnail",
        files={"file": ("a.png", png()[:150], "image/png")},
    )
    assert r.status_code == 422

# erifica se o serviço rejeita imagens cujo formato real nao corresponde ao MIME informado
def test_formato_real_diferente_do_declarado_422():
    r = client.post(
        "/internal/thumbnail",
        files={"file": ("a.png", imagem_em("JPEG"), "image/png")},
    )
    assert r.status_code == 422
    r = client.post(
        "/internal/thumbnail",
        files={"file": ("a.jpg", png(), "image/jpeg")},
    )
    assert r.status_code == 422

def test_formato_real_nao_permitido_415():
    r = client.post(
        "/internal/thumbnail",
        files={"file": ("a.png", imagem_em("BMP"), "image/png")},
    )
    assert r.status_code == 415

def test_limite_de_pixels_proprio_422(monkeypatch):
    monkeypatch.setattr(processamento, "LIMITE_PIXELS", 100)
    r = client.post("/internal/thumbnail", files={"file": ("a.png", png(), "image/png")})
    assert r.status_code == 422

def test_decompression_bomb_error_do_pillow_422(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    r = client.post("/internal/thumbnail", files={"file": ("a.png", png(), "image/png")})
    assert r.status_code == 422

def test_decompression_bomb_warning_vira_422(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 300_000)
    r = client.post("/internal/thumbnail", files={"file": ("a.png", png(), "image/png")})
    assert r.status_code == 422

def test_limite_de_pixels_configurado():
    assert Image.MAX_IMAGE_PIXELS == processamento.LIMITE_PIXELS

def test_png_transparente_vira_fundo_branco():
    b = io.BytesIO()
    Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(b, "PNG")
    miniatura = miniatura_de(b.getvalue(), "image/png")
    assert min(miniatura.getpixel((50, 50))) >= 240

def test_webp_transparente_vira_fundo_branco():
    b = io.BytesIO()
    Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(b, "WEBP")
    miniatura = miniatura_de(b.getvalue(), "image/webp")
    assert min(miniatura.getpixel((50, 50))) >= 240

def test_orientacao_exif_e_respeitada():
    exif = Image.Exif()
    exif[0x0112] = 6
    b = io.BytesIO()
    Image.new("RGB", (200, 100), "green").save(b, "JPEG", exif=exif)
    largura, altura = miniatura_de(b.getvalue(), "image/jpeg").size
    assert altura > largura