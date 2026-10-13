"""Sonda de CRC-16 para o protocolo P3.

Testa variantes comuns de CRC-16 contra as amostras reais capturadas
(ver docs/PROTOCOLO-P3.md sec. 4) para identificar o algoritmo usado
no campo `crc` do header. Rode: python tools/crc_probe.py
"""
from __future__ import annotations

# Amostras capturadas em 11/10/2026 (30s de escuta passiva em 192.168.0.50:5403)
AMOSTRAS = {
    "A (tor 0x1C, crc=0xC409)": "8E021B0009C400001C00010897497E7C3DBABD248104221604008F",
    "B (tor 0x02, crc=0xB5CC)": "8E021F00CCB5000002000102390007022300 0C 0179060100810422160400 8F".replace(" ", ""),
}


def crc16(dados: bytes, polinomio: int, init: int, refin: bool, refout: bool, xorout: int) -> int:
    """CRC-16 genérico (bitwise)."""
    def espelhar(v, bits):
        r = 0
        for _ in range(bits):
            r = (r << 1) | (v & 1)
            v >>= 1
        return r

    crc = init
    for byte in dados:
        if refin:
            byte = espelhar(byte, 8)
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ polinomio) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    if refout:
        crc = espelhar(crc, 16)
    return crc ^ xorout


ALGORITMOS = {
    "CCITT-FALSE": dict(polinomio=0x1021, init=0xFFFF, refin=False, refout=False, xorout=0x0000),
    "XMODEM":      dict(polinomio=0x1021, init=0x0000, refin=False, refout=False, xorout=0x0000),
    "KERMIT":      dict(polinomio=0x1021, init=0x0000, refin=True,  refout=True,  xorout=0x0000),
    "MCRF4XX":     dict(polinomio=0x1021, init=0xFFFF, refin=True,  refout=True,  xorout=0x0000),
    "ARC/IBM":     dict(polinomio=0x8005, init=0x0000, refin=True,  refout=True,  xorout=0x0000),
    "MODBUS":      dict(polinomio=0x8005, init=0xFFFF, refin=True,  refout=True,  xorout=0x0000),
    "USB":         dict(polinomio=0x8005, init=0xFFFF, refin=True,  refout=True,  xorout=0xFFFF),
    "MAXIM":       dict(polinomio=0x8005, init=0x0000, refin=True,  refout=True,  xorout=0xFFFF),
    "DNP":         dict(polinomio=0x3D65, init=0x0000, refin=True,  refout=True,  xorout=0xFFFF),
    "X-25":        dict(polinomio=0x1021, init=0xFFFF, refin=True,  refout=True,  xorout=0xFFFF),
}

# Intervalos candidatos sobre os quais o CRC seria calculado
def intervalos(dados: bytes):
    return {
        "payload(sem header)": dados[10:-1],
        "tudo menos start": dados[1:-1],
        "tudo exceto crc": dados[:4] + dados[6:-1],
        "tudo": dados,
        "payload+header": dados[:-1],
    }


def main():
    print("Procurando combinação (algoritmo x intervalo) que bata com as amostras...\n")
    achou = False
    for nome_alg, params in ALGORITMOS.items():
        for nome_intervalo in ("payload(sem header)", "tudo menos start",
                               "tudo exceto crc", "tudo", "payload+header"):
            ok = True
            for rotulo, hexstr in AMOSTRAS.items():
                dados = bytes.fromhex(hexstr)
                alvo = int.from_bytes(dados[4:6], "little")
                calculado = crc16(intervalos(dados)[nome_intervalo], **params)
                if calculado != alvo:
                    ok = False
                    break
            if ok:
                achou = True
                print(f"*** MATCH: {nome_alg} sobre '{nome_intervalo}' "
                      f"(bate com as {len(AMOSTRAS)} amostras)")
    if not achou:
        print("Nenhuma combinação bateu. Próximos passos possíveis:")
        print(" - capturar mais amostras e repetir;")
        print(" - testar CRC sobre ranges excluindo o próprio campo de tamanho;")
        print(" - inspecionar a rotina de CRC dentro do ZRound.exe (Delphi) com um "
              "disassembler.")


if __name__ == "__main__":
    main()
