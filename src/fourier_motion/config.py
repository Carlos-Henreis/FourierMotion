"""Configurações validadas do pipeline."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    samples: int = 2048
    threshold_percent: float = 0.05
    fps: int = 30
    duration: float = 60.0
    width: int = 1080
    height: int = 1920
    final_seconds: float = 6.0
    max_terms: int | None = None
    min_contour_length: float = 25.0
    max_contours: int = 128
    speed: str = "medium"

    def validate(self) -> None:
        if self.samples < 32 or self.samples % 2:
            raise ValueError("--samples deve ser par e >= 32")
        if not 0 < self.threshold_percent < 100:
            raise ValueError("--error deve estar entre 0 e 100 (exclusivo)")
        if self.fps <= 0 or self.duration <= 0 or self.width < 320 or self.height < 480:
            raise ValueError("FPS, duração e resolução devem ser positivos e adequados")
        if not 0 < self.final_seconds < self.duration:
            raise ValueError("--final-seconds deve estar entre 0 e a duração")
        if self.max_terms is not None and not 1 <= self.max_terms <= self.samples // 2:
            raise ValueError("--max-terms deve estar entre 1 e samples/2")
        if self.min_contour_length <= 0 or self.max_contours < 1:
            raise ValueError("Parâmetros de contorno inválidos")
        if self.speed not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"}:
            raise ValueError("Preset ffmpeg inválido")
