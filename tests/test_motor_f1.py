import unittest

from nucleo.motor_corrida import MotorCorrida
from nucleo.modelos import TipoSessao


class TestPassagemTeclado(unittest.TestCase):
    def setUp(self):
        self.motor = MotorCorrida(banco=None)
        self.motor.vincular_piloto(1, "Piloto")
        self.motor.iniciar(TipoSessao.TREINO)

    def test_primeira_tecla_abre_sem_criar_volta(self):
        volta = self.motor.adicionar_volta_por_tecla(1, agora_us=5_000_000)
        self.assertIsNone(volta)
        self.assertEqual([], self.motor._pilotos[1].voltas)
        self.assertEqual(5_000_000, self.motor._abertura_tecla_us[1])

    def test_segunda_tecla_fecha_e_terceira_fecha_proxima(self):
        self.assertIsNone(self.motor.adicionar_volta_por_tecla(1, agora_us=5_000_000))
        primeira = self.motor.adicionar_volta_por_tecla(1, agora_us=14_500_000)
        self.assertIsNotNone(primeira)
        self.assertEqual(9_500_000, primeira.tempo_us)
        self.assertEqual(1, primeira.numero)

        segunda = self.motor.adicionar_volta_por_tecla(1, agora_us=24_000_000)
        self.assertIsNotNone(segunda)
        self.assertEqual(9_500_000, segunda.tempo_us)
        self.assertEqual(2, segunda.numero)
        self.assertEqual(2, len(self.motor._pilotos[1].voltas))

    def test_tempo_minimo_tambem_e_respeitado_no_teclado(self):
        self.motor.tempo_minimo_volta_us = 5_000_000
        self.assertIsNone(self.motor.adicionar_volta_por_tecla(1, agora_us=1_000_000))
        self.assertIsNone(self.motor.adicionar_volta_por_tecla(1, agora_us=4_000_000))
        self.assertEqual([], self.motor._pilotos[1].voltas)

        volta = self.motor.adicionar_volta_por_tecla(1, agora_us=7_000_000)
        self.assertIsNotNone(volta)
        self.assertEqual(6_000_000, volta.tempo_us)


if __name__ == "__main__":
    unittest.main()
