"""Configurações validadas do pipeline."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    preset: str = "classic"
    samples: int = 2048
    threshold_percent: float = 0.05
    fps: int = 30
    duration: float = 60.0
    width: int = 1080
    height: int = 1920
    final_seconds: float = 5.0
    max_terms: int | None = None
    min_contour_length: float = 25.0
    max_contours: int = 128
    speed: str = "medium"
    target_fill_ratio: float = 0.68
    cycle_seconds: float = 3.5
    flash_seconds: float = 3.0
    transition_seconds: float = 0.4
    visual_max_terms: int = 200
    stage_terms: tuple[int, ...] = (1, 2, 5, 15, 40, 100, 150, 200)
    hook_text: str = ""

    def validate(self) -> None:
        if self.preset not in {"classic", "viral"}:
            raise ValueError("--preset deve ser classic ou viral")
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
        if not 0.4 <= self.target_fill_ratio <= 0.95:
            raise ValueError("--target-fill-ratio deve ficar entre 0.4 e 0.95")
        if not 2.5 <= self.cycle_seconds <= 6:
            raise ValueError("--cycle-seconds deve ficar entre 2.5 e 6")
        if not 0 <= self.flash_seconds < self.duration - self.final_seconds:
            raise ValueError("--flash-seconds deve deixar tempo para a animação e a tela final")
        if not 0 <= self.transition_seconds <= 2.0:
            raise ValueError("--transition-seconds deve ficar entre 0 e 2")
        if not 1 <= self.visual_max_terms <= self.samples // 2:
            raise ValueError("--visual-max-terms deve ficar entre 1 e samples/2")
        if not self.stage_terms or any(n < 1 for n in self.stage_terms):
            raise ValueError("--stage-terms deve conter valores positivos")
        if self.speed not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"}:
            raise ValueError("Preset ffmpeg inválido")
