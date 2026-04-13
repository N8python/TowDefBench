from __future__ import annotations

import argparse
import json
import math
import textwrap
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pygame

from cli_client import (
    CLEAR_FAILURE_MESSAGES,
    DEPLOY_FAILURE_MESSAGES,
    RESOURCE_LABEL,
    ROSTER_ALIASES,
    display_name_for,
    format_special_state,
)
from game_server import (
    Skeleton,
    Orc,
    Backstabber,
    Grenade,
    Crusher,
    FreezeMine,
    Goblin,
    Necromancer,
    Herald,
    AcidSprayer,
    LineBomb,
    Level,
    Cannon,
    Vortex,
    Berserker,
    Gargoyle,
    Golem,
    Leaper,
    Turret,
    QuadTurret,
    LandMine,
    DoubleTurret,
    Imp,
    IceTurret,
    PowerPlant,
    ForceWall,
    Barricade,
    Monster,
    Juggernaut,
    build_demo_level,
)
from trajectory_logging import TrajectoryLogger

SCREEN_WIDTH = 1360
SCREEN_HEIGHT = 720
BOARD_LEFT = 42
BOARD_TOP = 226
TILE_WIDTH = 92
TILE_HEIGHT = 84
CARD_HEIGHT = 74
CARD_GAP = 8
FPS = 60
MESSAGE_DURATION = 2.8
BANNER_DURATION = 2.4
MONSTER_BOUNDS_INSET_X = 8
MONSTER_BOUNDS_INSET_TOP = 4
MONSTER_BOUNDS_INSET_BOTTOM = 4
MONSTER_SHADOW_HEIGHT = 12
MONSTER_SHADOW_BOTTOM_INSET = 4
DEFENSE_BOUNDS_INSET_X = 8
DEFENSE_BOUNDS_INSET_TOP = 22
DEFENSE_BOUNDS_INSET_BOTTOM = 8
DEFENSE_SHADOW_HEIGHT = 10
DEFENSE_SHADOW_BOTTOM_INSET = 4
DEFENSE_SPECIAL_BADGE_WIDTH = 20
DEFENSE_SPECIAL_BADGE_HEIGHT = 16
DEFENSE_SPECIAL_BADGE_MARGIN = 8
DEFENSE_SPECIAL_BADGE_GAP = 2
HUD_TO_LOADOUT_TRAY_GAP = 10
LOADOUT_TRAY_TO_BOARD_GAP = 10
LOADOUT_CARD_SHADOW_DEPTH = 6
LOADOUT_CARD_VERTICAL_PADDING = 4
TRAY_INSET = 10
ENERGY_BANK_WIDTH = 90
CLEAR_SLOT_WIDTH = 76
TRAY_SLOT_GAP = 10
CARD_INSET_X = 3
CARD_INSET_Y = 3
CARD_STATUS_SIZE = 18
CARD_STATUS_MARGIN = 3
CARD_PANEL_BOTTOM_GAP = 2
CARD_COST_HEIGHT = 12
CARD_CONTENT_PADDING = 2

ROOT = Path(__file__).resolve().parent
ASSET_DIR = ROOT / "assets" / "imagegen" / "td-roster-v1"

ASSET_FILENAMES = {
    "Turret": "turret.png",
    "QuadTurret": "quadturret.png",
    "PowerPlant": "powerplant.png",
    "Backstabber": "backstabber.png",
    "IceTurret": "iceturret.png",
    "Cannon": "cannon.png",
    "Vortex": "vortex.png",
    "LineBomb": "linebomb.png",
    "DoubleTurret": "doubleturret.png",
    "Crusher": "crusher.png",
    "CrusherRecharging": "crusher.png",
    "Barricade": "barricade.png",
    "ForceWall": "forcewall.png",
    "AcidSprayer": "acidsprayer.png",
    "Grenade": "grenade.png",
    "LandMine": "landmine.png",
    "FreezeMine": "freezemine.png",
    "Skeleton": "skeleton.png",
    "Herald": "herald.png",
    "Imp": "imp.png",
    "Goblin": "goblin.png",
    "Orc": "orc.png",
    "Leaper": "leaper.png",
    "LeaperGrounded": "leaper.png",
    "Necromancer": "necromancer.png",
    "Berserker": "berserker.png",
    "BerserkerEnraged": "berserker.png",
    "Gargoyle": "gargoyle.png",
    "Juggernaut": "juggernaut.png",
    "Golem": "golem.png",
    "Energy": "energy.png",
}

CARD_COLORS = {
    Turret: ((136, 148, 158), (74, 84, 92)),
    QuadTurret: ((104, 128, 162), (54, 67, 88)),
    PowerPlant: ((214, 175, 86), (124, 92, 34)),
    Backstabber: ((108, 136, 118), (54, 71, 60)),
    IceTurret: ((132, 168, 188), (63, 91, 109)),
    Cannon: ((128, 139, 114), (70, 78, 63)),
    Vortex: ((122, 106, 158), (68, 55, 92)),
    LineBomb: ((208, 112, 70), (116, 58, 36)),
    DoubleTurret: ((120, 138, 144), (63, 76, 82)),
    Crusher: ((140, 126, 154), (78, 65, 92)),
    Barricade: ((154, 133, 108), (88, 72, 56)),
    ForceWall: ((114, 118, 126), (63, 67, 74)),
    AcidSprayer: ((132, 154, 98), (72, 87, 54)),
    Grenade: ((186, 84, 74), (104, 42, 38)),
    LandMine: ((152, 140, 100), (86, 74, 48)),
    FreezeMine: ((144, 182, 206), (73, 96, 118)),
}

ENTITY_CLASS_BY_NAME = {
    cls.__name__: cls
    for cls in (
        Turret,
        QuadTurret,
        PowerPlant,
        Backstabber,
        IceTurret,
        Cannon,
        Vortex,
        LineBomb,
        DoubleTurret,
        Crusher,
        Barricade,
        ForceWall,
        AcidSprayer,
        Grenade,
        LandMine,
        FreezeMine,
        Skeleton,
        Herald,
        Imp,
        Goblin,
        Orc,
        Leaper,
        Necromancer,
        Berserker,
        Gargoyle,
        Golem,
        Juggernaut,
    )
}

DEFENSE_CLASS_BY_NAME = {
    cls.__name__: cls
    for cls in (
        Turret,
        QuadTurret,
        PowerPlant,
        Backstabber,
        IceTurret,
        Cannon,
        Vortex,
        LineBomb,
        DoubleTurret,
        Crusher,
        Barricade,
        ForceWall,
        AcidSprayer,
        Grenade,
        LandMine,
        FreezeMine,
    )
}


@dataclass
class Button:
    rect: pygame.Rect
    label: str


@dataclass
class ReplayFrame:
    index: int
    trigger: str
    command: str | None
    result: str
    snapshot: dict


@dataclass
class ReplayTile:
    row: int
    col: int
    occupant: object | None = None


class ReplayBoard:
    def __init__(self, rows: int, cols: int, turn_count: int, end_state: str | None):
        self.rows = rows
        self.cols = cols
        self.turn_count = turn_count
        self.end_state = end_state
        self.tiles = [[ReplayTile(row=row, col=col) for col in range(cols)] for row in range(rows)]


class ReplayDeployClient:
    def __init__(self, cooldowns: dict):
        self.cooldowns = cooldowns


class ReplayLevelDefinition:
    def __init__(self, snapshot: dict):
        self.name = snapshot["level_name"]
        self.rows = snapshot["rows"]
        self.cols = snapshot["cols"]
        self.deployable_cols = snapshot.get("deployable_cols", self.cols)
        self.total_waves = snapshot["total_waves"]
        self.major_wave_interval = snapshot["major_wave_interval"]
        self.defense_roster = tuple(DEFENSE_CLASS_BY_NAME[name] for name in snapshot["defense_roster"])

    def is_major_wave(self, wave_number: int) -> bool:
        return wave_number % self.major_wave_interval == 0


class ReplayLevel:
    def __init__(self, snapshot: dict):
        self.definition = ReplayLevelDefinition(snapshot)
        self.energy = snapshot["energy"]
        self.spawned_waves = snapshot["spawned_waves"]
        self.board = ReplayBoard(
            rows=snapshot["rows"],
            cols=snapshot["cols"],
            turn_count=snapshot["turn_count"],
            end_state=snapshot["end_state"],
        )
        self.deploy_client = ReplayDeployClient(
            cooldowns={
                DEFENSE_CLASS_BY_NAME[name]: cooldown
                for name, cooldown in snapshot["cooldowns"].items()
                if name in DEFENSE_CLASS_BY_NAME
            }
        )
        self.clear_client = None

        for occupant_data in snapshot["occupants"]:
            entity_cls = ENTITY_CLASS_BY_NAME.get(occupant_data["class_name"])
            if entity_cls is None:
                continue
            occupant = entity_cls()
            occupant.hp = occupant_data["hp"]
            if "turns_to_generate" in occupant_data:
                occupant.turns_to_generate = occupant_data["turns_to_generate"]
            if "turns_to_arm" in occupant_data:
                occupant.turns_to_arm = occupant_data["turns_to_arm"]
            if "turns_to_digest" in occupant_data:
                occupant.turns_to_digest = occupant_data["turns_to_digest"]
            if "ready_to_fire" in occupant_data:
                occupant.ready_to_fire = occupant_data["ready_to_fire"]
            if "has_vaulted" in occupant_data:
                occupant.has_vaulted = occupant_data["has_vaulted"]
            if "pace_phase" in occupant_data:
                occupant.pace_phase = occupant_data["pace_phase"]
            if "action_count" in occupant_data:
                occupant.action_count = occupant_data["action_count"]
            if "enraged" in occupant_data:
                occupant.enraged = occupant_data["enraged"]
            if "awakened" in occupant_data:
                occupant.awakened = occupant_data["awakened"]
            if "move_phase" in occupant_data:
                occupant.move_phase = occupant_data["move_phase"]
            if "speed" in occupant_data:
                occupant.speed = occupant_data["speed"]
            if "attack_damage" in occupant_data:
                occupant.attack_damage = occupant_data["attack_damage"]
            if "has_moved_once" in occupant_data:
                occupant.has_moved_once = occupant_data["has_moved_once"]
            if isinstance(occupant, Monster):
                occupant.wave_number = occupant_data.get("wave_number")
                occupant.skip_next_action = occupant_data.get("skip_next_action", False)
                occupant.counts_toward_wave_health = occupant_data.get("counts_toward_wave_health", True)
                occupant.frozen_turns = occupant_data.get("frozen_turns", 0)
                occupant.chilled = occupant_data.get("chilled", False)
                occupant.chill_phase = occupant_data.get("chill_phase", 0)
            row = occupant_data["row"]
            col = occupant_data["col"]
            tile = self.board.tiles[row][col]
            tile.occupant = occupant
            occupant.board = self.board
            occupant.level = self
            occupant.tile = tile

    @property
    def end_state(self):
        return self.board.end_state

    @property
    def turn_count(self):
        return self.board.turn_count


class GameApp:
    def __init__(
        self,
        level_factory: Callable[[], Level] | None = None,
        replay_frames: list[ReplayFrame] | None = None,
        replay_delay: float = 1.0,
        trajectory_logger: TrajectoryLogger | None = None,
        replay_log_path: Path | None = None,
        follow_replay_log: bool = False,
    ):
        if level_factory is None and not replay_frames:
            raise ValueError("GameApp requires either a live level factory or replay frames.")

        self.level_factory = level_factory
        self.trajectory_logger = None if replay_frames else trajectory_logger
        self.replay_mode = bool(replay_frames)
        self.replay_frames = replay_frames or []
        self.replay_log_path = replay_log_path if self.replay_mode else None
        self.follow_replay_log = bool(self.replay_mode and follow_replay_log and replay_log_path is not None)
        self.replay_delay = max(0.05, replay_delay)
        self.replay_index = 0
        self.replay_paused = False
        self.replay_finished = False
        self.next_replay_time = time.time() + self.replay_delay

        if self.replay_mode:
            self.level = ReplayLevel(self.replay_frames[0].snapshot)
        else:
            self.level = level_factory()
        self.selected_defense_cls = None
        self.clear_selected = False
        self.hovered_tile = None
        self.last_message = (
            "Live mirror loaded. Space pauses, Left/Right step, and R rewinds loaded states."
            if self.follow_replay_log
            else "Replay loaded. Space pauses, Left/Right step, and R restarts the replay."
            if self.replay_mode
            else "Pick a defense card or remove tool, then click the grid. Press Space to end the turn."
        )
        self.message_until = time.time() + 6.0
        self.banner_text = None
        self.banner_until = 0.0
        self.previous_spawned_waves = self.level.spawned_waves
        self.event_log = deque(maxlen=6)
        self.hover_validity = None
        self.running = True
        self.sync_layout()

        pygame.display.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("Tower Defense Benchmark")
        self.clock = pygame.time.Clock()

        self.title_font = pygame.font.SysFont("georgia", 38, bold=True)
        self.subtitle_font = pygame.font.SysFont("georgia", 21)
        self.hud_font = pygame.font.SysFont("trebuchetms", 25, bold=True)
        self.body_font = pygame.font.SysFont("trebuchetms", 19)
        self.small_font = pygame.font.SysFont("trebuchetms", 16)
        self.tiny_font = pygame.font.SysFont("trebuchetms", 14)
        self.packet_bubble_font = pygame.font.SysFont("trebuchetms", 12, bold=True)
        self.packet_cost_font = pygame.font.SysFont("trebuchetms", 12, bold=True)

        self.base_hp = {}
        for entity_cls in (
            Turret,
            QuadTurret,
            PowerPlant,
            Backstabber,
            IceTurret,
            Cannon,
            Vortex,
            LineBomb,
            DoubleTurret,
            Crusher,
            Barricade,
            ForceWall,
            AcidSprayer,
            Grenade,
            LandMine,
            FreezeMine,
            Skeleton,
            Herald,
            Imp,
            Goblin,
            Orc,
            Leaper,
            Necromancer,
            Berserker,
            Gargoyle,
            Golem,
            Juggernaut,
        ):
            self.base_hp[entity_cls] = entity_cls().hp

        self.asset_paths = {name: ASSET_DIR / filename for name, filename in ASSET_FILENAMES.items()}
        self.images = self.load_images()

        if self.replay_mode:
            self.apply_replay_frame(0, reset_timing=True)
        elif self.trajectory_logger is not None:
            self.trajectory_logger.log_board_snapshot(
                self.level,
                trigger="initial",
                command=None,
                result="Initial board state.",
            )

    def sync_layout(self):
        self.board_rows = self.level.board.rows
        self.board_cols = self.level.board.cols
        self.deployable_cols = getattr(self.level.definition, "deployable_cols", self.board_cols)
        self.entry_col = self.board_cols - 1
        self.board_width = TILE_WIDTH * self.board_cols
        self.board_height = TILE_HEIGHT * self.board_rows
        self.board_rect = pygame.Rect(BOARD_LEFT, BOARD_TOP, self.board_width, self.board_height)
        self.board_frame_rect = pygame.Rect(BOARD_LEFT - 22, BOARD_TOP - 22, self.board_width + 44, self.board_height + 44)
        self.hud_rect = pygame.Rect(28, 20, SCREEN_WIDTH - 56, 78)
        loadout_tray_top = self.hud_rect.bottom + HUD_TO_LOADOUT_TRAY_GAP
        loadout_tray_bottom = self.board_frame_rect.top - LOADOUT_TRAY_TO_BOARD_GAP
        self.loadout_tray_rect = pygame.Rect(28, loadout_tray_top, SCREEN_WIDTH - 56, loadout_tray_bottom - loadout_tray_top)
        self.tray_inner_rect = self.loadout_tray_rect.inflate(-TRAY_INSET * 2, -8)
        self.energy_bank_rect = pygame.Rect(
            self.tray_inner_rect.x,
            self.tray_inner_rect.y,
            ENERGY_BANK_WIDTH,
            self.tray_inner_rect.height,
        )
        self.clear_rect = pygame.Rect(
            self.tray_inner_rect.right - CLEAR_SLOT_WIDTH,
            self.tray_inner_rect.y,
            CLEAR_SLOT_WIDTH,
            self.tray_inner_rect.height,
        )
        self.card_slot_area_rect = pygame.Rect(
            self.energy_bank_rect.right + TRAY_SLOT_GAP,
            self.tray_inner_rect.y + LOADOUT_CARD_VERTICAL_PADDING,
            self.clear_rect.left - self.energy_bank_rect.right - TRAY_SLOT_GAP * 2,
            self.tray_inner_rect.height - LOADOUT_CARD_VERTICAL_PADDING * 2,
        )
        self.loadout_card_height = max(
            48,
            min(CARD_HEIGHT - 12, self.card_slot_area_rect.height - LOADOUT_CARD_SHADOW_DEPTH),
        )
        self.loadout_card_top = self.card_slot_area_rect.y + (
            self.card_slot_area_rect.height - self.loadout_card_height - LOADOUT_CARD_SHADOW_DEPTH
        ) // 2
        roster_count = max(1, len(self.level.definition.defense_roster))
        available_card_width = (self.card_slot_area_rect.width - CARD_GAP * (roster_count - 1)) // roster_count
        desired_card_width = self.loadout_card_height + 6
        self.loadout_card_width = min(available_card_width, max(58, desired_card_width))
        self.loadout_card_left = self.card_slot_area_rect.x
        self.sidebar_left = BOARD_LEFT + self.board_width + 28
        self.sidebar_width = SCREEN_WIDTH - self.sidebar_left - 28
        self.sidebar_top = BOARD_TOP - 2
        self.sidebar_bottom = BOARD_TOP + self.board_height
        self.sidebar_height = self.sidebar_bottom - self.sidebar_top
        self.info_panel_rect = pygame.Rect(self.sidebar_left, self.sidebar_top, self.sidebar_width, self.sidebar_height)
        self.end_turn_button = Button(
            rect=pygame.Rect(self.sidebar_left + 18, self.sidebar_bottom - 112, self.sidebar_width - 36, 48),
            label="End Turn",
        )
        self.restart_button = Button(
            rect=pygame.Rect(self.sidebar_left + 18, self.sidebar_bottom - 56, self.sidebar_width - 36, 36),
            label="Restart Level",
        )

    def reset_level(self):
        if self.replay_mode:
            self.reset_replay()
            return
        self.level = self.level_factory()
        self.sync_layout()
        self.clear_selection()
        self.previous_spawned_waves = self.level.spawned_waves
        self.push_message("Level restarted.")
        self.event_log.clear()
        self.log_trajectory(trigger="restart", command="restart", result="Level restarted.")

    def reset_replay(self):
        self.replay_finished = False
        self.replay_paused = False
        self.apply_replay_frame(0, reset_timing=True)
        self.push_message("Mirror rewound." if self.follow_replay_log else "Replay restarted.")

    def apply_replay_frame(self, index: int, reset_timing: bool = False):
        frame = self.replay_frames[index]
        self.replay_index = index
        self.level = ReplayLevel(frame.snapshot)
        self.sync_layout()
        self.clear_selection()
        self.previous_spawned_waves = self.level.spawned_waves
        self.event_log.clear()
        if frame.command:
            self.event_log.appendleft(frame.command)
        result = frame.result.strip().splitlines()[0] if frame.result.strip() else None
        if result and result != self.level.definition.name:
            self.event_log.appendleft(result)
        if frame.command:
            self.push_message(f"[{index + 1}/{len(self.replay_frames)}] {frame.command}")
        else:
            self.push_message(f"[{index + 1}/{len(self.replay_frames)}] Initial board state.")
        if reset_timing:
            self.next_replay_time = time.time() + self.replay_delay

    def step_replay(self, direction: int):
        if not self.replay_mode:
            return
        next_index = max(0, min(len(self.replay_frames) - 1, self.replay_index + direction))
        if next_index == self.replay_index:
            if next_index == len(self.replay_frames) - 1:
                if self.follow_replay_log:
                    self.push_message("At latest mirrored state.")
                else:
                    self.replay_finished = True
                    self.push_message("Replay finished.")
            return
        self.replay_finished = False
        self.apply_replay_frame(next_index, reset_timing=True)

    def refresh_replay_frames(self):
        if not self.follow_replay_log or self.replay_log_path is None:
            return
        try:
            frames = load_replay_frames(self.replay_log_path)
        except SystemExit:
            return
        if len(frames) <= len(self.replay_frames):
            return
        self.replay_frames = frames
        self.replay_finished = False

    def update_replay(self):
        if not self.replay_mode:
            return
        self.refresh_replay_frames()
        if self.replay_paused or self.replay_finished:
            return
        if time.time() < self.next_replay_time:
            return
        if self.replay_index + 1 >= len(self.replay_frames):
            if self.follow_replay_log:
                self.next_replay_time = time.time() + min(self.replay_delay, 0.25)
                return
            self.replay_finished = True
            self.push_message("Replay finished. Close the window or press R to replay it again.")
            return
        self.apply_replay_frame(self.replay_index + 1, reset_timing=True)

    def clear_selection(self):
        self.selected_defense_cls = None
        self.clear_selected = False

    def select_defense(self, defense_cls):
        self.selected_defense_cls = defense_cls
        self.clear_selected = False

    def select_clear(self):
        self.selected_defense_cls = None
        self.clear_selected = True

    def has_selected_tool(self):
        return self.selected_defense_cls is not None or self.clear_selected

    def load_images(self):
        image_sizes = {
            "Turret": (74, 74),
            "QuadTurret": (80, 76),
            "PowerPlant": (74, 74),
            "Backstabber": (72, 72),
            "IceTurret": (74, 74),
            "Cannon": (82, 74),
            "Vortex": (78, 74),
            "LineBomb": (74, 74),
            "DoubleTurret": (78, 74),
            "Crusher": (78, 76),
            "CrusherRecharging": (76, 70),
            "Barricade": (66, 66),
            "ForceWall": (74, 82),
            "AcidSprayer": (74, 72),
            "Grenade": (76, 76),
            "LandMine": (70, 54),
            "FreezeMine": (72, 56),
            "Skeleton": (66, 72),
            "Herald": (78, 74),
            "Imp": (64, 66),
            "Goblin": (72, 74),
            "Orc": (74, 76),
            "Leaper": (84, 78),
            "LeaperGrounded": (66, 74),
            "Necromancer": (78, 76),
            "Berserker": (74, 76),
            "BerserkerEnraged": (70, 76),
            "Gargoyle": (82, 80),
            "Juggernaut": (96, 64),
            "Golem": (96, 78),
            "Energy": (38, 38),
        }

        images = {}
        for name, size in image_sizes.items():
            asset_path = self.asset_paths[name]
            if asset_path.exists():
                try:
                    image = pygame.image.load(str(asset_path)).convert_alpha()
                    if name != "Energy":
                        image = self.prepare_image(image)
                    image = self.scale_to_fit(image, size)
                    if name == "Energy":
                        images[name] = image
                        continue
                    if "Monster" in name:
                        image = self.fit_opaque_bounds(
                            image,
                            (
                                TILE_WIDTH - MONSTER_BOUNDS_INSET_X * 2,
                                TILE_HEIGHT - MONSTER_BOUNDS_INSET_TOP - MONSTER_BOUNDS_INSET_BOTTOM,
                            ),
                        )
                    else:
                        reserved_width = TILE_WIDTH - DEFENSE_BOUNDS_INSET_X * 2
                        if name in {"PowerPlant", "LandMine", "FreezeMine", "Crusher", "CrusherRecharging", "Cannon"}:
                            reserved_width -= DEFENSE_SPECIAL_BADGE_WIDTH + DEFENSE_SPECIAL_BADGE_GAP
                        image = self.fit_opaque_bounds(
                            image,
                            (
                                reserved_width,
                                TILE_HEIGHT - DEFENSE_BOUNDS_INSET_TOP - DEFENSE_BOUNDS_INSET_BOTTOM,
                            ),
                        )
                    images[name] = image
                    continue
                except pygame.error:
                    pass
            images[name] = self.make_fallback_sprite(name, size)
        self.chilled_images = {name: self.tint_surface(image, (158, 214, 255)) for name, image in images.items()}
        self.frozen_images = {name: self.tint_surface(image, (138, 224, 255)) for name, image in images.items()}
        self.awakened_images = {
            "Gargoyle": self.tint_surface(images["Gargoyle"], (232, 164, 114))
        } if "Gargoyle" in images else {}
        return images

    def normalize_asset(self, asset_path: Path):
        try:
            surface = pygame.image.load(str(asset_path))
            pygame.image.save(surface, str(asset_path))
        except pygame.error:
            return

    def prepare_image(self, image: pygame.Surface) -> pygame.Surface:
        surface = image.copy().convert_alpha()
        if self.has_transparent_border(surface):
            rect = surface.get_bounding_rect(min_alpha=1)
            if rect.width and rect.height:
                return surface.subsurface(rect).copy()
            return surface
        return self.cleanup_background(surface)

    def has_transparent_border(self, image: pygame.Surface) -> bool:
        width, height = image.get_size()
        if width == 0 or height == 0:
            return False

        border_alpha = []
        for x in range(width):
            border_alpha.append(image.get_at((x, 0)).a)
            border_alpha.append(image.get_at((x, height - 1)).a)
        for y in range(height):
            border_alpha.append(image.get_at((0, y)).a)
            border_alpha.append(image.get_at((width - 1, y)).a)

        transparent_pixels = sum(alpha <= 8 for alpha in border_alpha)
        return transparent_pixels >= len(border_alpha) * 0.3

    def cleanup_background(self, image: pygame.Surface) -> pygame.Surface:
        surface = image.copy().convert_alpha()
        width, height = surface.get_size()
        if width == 0 or height == 0:
            return surface

        border_colors = []
        for x in range(width):
            border_colors.append(surface.get_at((x, 0)))
            border_colors.append(surface.get_at((x, height - 1)))
        for y in range(height):
            border_colors.append(surface.get_at((0, y)))
            border_colors.append(surface.get_at((width - 1, y)))

        opaque_colors = [color for color in border_colors if color.a > 8]
        if not opaque_colors:
            return surface

        quantized = Counter((color.r // 16, color.g // 16, color.b // 16) for color in opaque_colors)
        dominant_key, _ = quantized.most_common(1)[0]
        matching = [
            color for color in opaque_colors
            if (color.r // 16, color.g // 16, color.b // 16) == dominant_key
        ]
        bg = pygame.Color(
            sum(color.r for color in matching) // len(matching),
            sum(color.g for color in matching) // len(matching),
            sum(color.b for color in matching) // len(matching),
            255,
        )

        def is_background(color: pygame.Color) -> bool:
            if color.a <= 8:
                return True
            dr = color.r - bg.r
            dg = color.g - bg.g
            db = color.b - bg.b
            distance_sq = dr * dr + dg * dg + db * db
            greenish = color.g > color.r + 12 and color.g > color.b + 12 and bg.g > bg.r and bg.g > bg.b
            return distance_sq <= 85 * 85 or (greenish and distance_sq <= 115 * 115)

        queue = deque()
        seen = set()
        for x in range(width):
            queue.append((x, 0))
            queue.append((x, height - 1))
        for y in range(height):
            queue.append((0, y))
            queue.append((width - 1, y))

        while queue:
            x, y = queue.popleft()
            if (x, y) in seen:
                continue
            seen.add((x, y))
            color = surface.get_at((x, y))
            if not is_background(color):
                continue
            surface.set_at((x, y), pygame.Color(color.r, color.g, color.b, 0))
            if x > 0:
                queue.append((x - 1, y))
            if x < width - 1:
                queue.append((x + 1, y))
            if y > 0:
                queue.append((x, y - 1))
            if y < height - 1:
                queue.append((x, y + 1))

        rect = surface.get_bounding_rect(min_alpha=1)
        if rect.width and rect.height:
            surface = surface.subsurface(rect).copy()
        return surface

    def scale_to_fit(self, image: pygame.Surface, size: tuple[int, int]) -> pygame.Surface:
        max_width, max_height = size
        width, height = image.get_size()
        if width == 0 or height == 0:
            return image
        scale = min(max_width / width, max_height / height)
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        return pygame.transform.smoothscale(image, new_size)

    def fit_opaque_bounds(self, image: pygame.Surface, size: tuple[int, int]) -> pygame.Surface:
        max_width, max_height = size
        bounds = image.get_bounding_rect(min_alpha=1)
        if bounds.width == 0 or bounds.height == 0:
            return image
        scale = min(max_width / bounds.width, max_height / bounds.height, 1.0)
        if scale >= 0.999:
            return image
        width, height = image.get_size()
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        return pygame.transform.smoothscale(image, new_size)

    def make_fallback_sprite(self, name: str, size: tuple[int, int]) -> pygame.Surface:
        width, height = size
        sprite = pygame.Surface(size, pygame.SRCALPHA)
        monster_names = {"Skeleton", "Herald", "Goblin", "Orc", "Leaper", "Necromancer", "Berserker", "Juggernaut"}
        color = (102, 186, 82) if name not in monster_names else (141, 152, 112)
        accent = (247, 206, 85) if name in {"PowerPlant", "Energy"} else (89, 57, 39)
        pygame.draw.ellipse(sprite, color, (4, 8, width - 8, height - 12))
        pygame.draw.ellipse(sprite, (255, 255, 255), (width * 0.25, height * 0.3, width * 0.18, height * 0.18))
        pygame.draw.ellipse(sprite, (255, 255, 255), (width * 0.55, height * 0.3, width * 0.18, height * 0.18))
        pygame.draw.circle(sprite, (24, 24, 24), (int(width * 0.34), int(height * 0.39)), max(2, width // 26))
        pygame.draw.circle(sprite, (24, 24, 24), (int(width * 0.63), int(height * 0.39)), max(2, width // 26))
        pygame.draw.arc(sprite, accent, (width * 0.28, height * 0.52, width * 0.42, height * 0.18), math.pi * 0.05, math.pi * 0.95, 3)
        return sprite

    def tint_surface(self, image: pygame.Surface, tint_rgb: tuple[int, int, int]) -> pygame.Surface:
        tinted = image.copy().convert_alpha()
        overlay = pygame.Surface(tinted.get_size(), pygame.SRCALPHA)
        overlay.fill((*tint_rgb, 72))
        tinted.blit(overlay, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
        return tinted

    def run(self):
        while self.running:
            self.process_events()
            self.draw()
            pygame.display.flip()
            self.clock.tick(FPS)
        if self.trajectory_logger is not None:
            self.trajectory_logger.close(self.level)
        pygame.quit()

    def process_events(self):
        mouse_pos = pygame.mouse.get_pos()
        self.hovered_tile = self.tile_at_pos(mouse_pos)
        self.hover_validity = None if self.replay_mode else self.preview_validity()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self.handle_keydown(event.key)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.handle_click(event.pos)

        self.update_replay()

    def handle_keydown(self, key: int):
        if self.replay_mode:
            if key in (pygame.K_ESCAPE, pygame.K_q):
                self.running = False
            elif key == pygame.K_r:
                self.reset_replay()
            elif key in (pygame.K_SPACE, pygame.K_RETURN):
                self.replay_paused = not self.replay_paused
                state = "paused" if self.replay_paused else "resumed"
                self.push_message(f"Replay {state}.")
                if not self.replay_paused:
                    self.next_replay_time = time.time() + self.replay_delay
            elif key == pygame.K_RIGHT:
                self.replay_paused = True
                self.step_replay(1)
            elif key == pygame.K_LEFT:
                self.replay_paused = True
                self.step_replay(-1)
            return

        roster = self.level.definition.defense_roster
        if key == pygame.K_ESCAPE:
            self.clear_selection()
        elif key == pygame.K_r:
            self.reset_level()
        elif key == pygame.K_s:
            self.select_clear()
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            self.end_turn()
        elif pygame.K_1 <= key <= pygame.K_9:
            index = key - pygame.K_1
            if index < len(roster):
                self.select_defense(roster[index])

    def handle_click(self, pos: tuple[int, int]):
        if self.replay_mode:
            return
        if self.end_turn_button.rect.collidepoint(pos):
            self.end_turn()
            return
        if self.restart_button.rect.collidepoint(pos):
            self.reset_level()
            return
        if self.clear_rect.collidepoint(pos):
            self.select_clear()
            return

        card_clicked = self.card_at_pos(pos)
        if card_clicked is not None:
            self.select_defense(card_clicked)
            return

        tile = self.tile_at_pos(pos)
        if tile is not None:
            if self.clear_selected:
                self.try_clear(tile[0], tile[1])
            elif self.selected_defense_cls is not None:
                self.try_deploy(self.selected_defense_cls, tile[0], tile[1])

    def card_at_pos(self, pos: tuple[int, int]):
        for index, defense_cls in enumerate(self.level.definition.defense_roster):
            if self.card_rect(index).collidepoint(pos):
                return defense_cls
        return None

    def try_deploy(self, defense_cls, row: int, col: int):
        success, reason = self.level.deploy_defense(defense_cls, row, col)
        if success:
            result = f"Deployed {self.display_name(defense_cls)} at row {row + 1}, column {col + 1}."
            self.push_message(result)
            self.event_log.appendleft(f"Deployed {self.display_name(defense_cls)} in lane {row + 1}.")
            alias = ROSTER_ALIASES.get(defense_cls.__name__, defense_cls.__name__.lower())
            self.log_trajectory(
                trigger="deploy",
                command=f"deploy {alias} {row + 1} {col + 1}",
                result=result,
            )
        else:
            reason_text = self.display_placement_reason(reason)
            self.push_message(f"Could not deploy {self.display_name(defense_cls)}: {reason_text}.")

    def try_clear(self, row: int, col: int):
        success, reason = self.level.clear_defense(row, col)
        if success:
            result = f"Cleared defense at row {row + 1}, column {col + 1}."
            self.push_message(result)
            self.event_log.appendleft(f"Cleared lane {row + 1}.")
            self.log_trajectory(
                trigger="clear",
                command=f"clear {row + 1} {col + 1}",
                result=result,
            )
        else:
            reason_text = CLEAR_FAILURE_MESSAGES.get(reason, reason or "clear failed")
            self.push_message(f"Could not clear tile: {reason_text}.")

    def preview_validity(self):
        if self.hovered_tile is None:
            return None
        row, col = self.hovered_tile
        if self.clear_selected:
            reason = self.level.clear_client.clear_failure_reason(row, col)
            return reason is None, reason
        if self.selected_defense_cls is None:
            return None
        reason = self.level.deploy_client.deployment_failure_reason(self.selected_defense_cls, row, col)
        return reason is None, reason

    def display_placement_reason(self, reason: str | None) -> str:
        if reason is None:
            return "deployment failed"
        return DEPLOY_FAILURE_MESSAGES.get(reason, reason)

    def end_turn(self):
        if self.level.end_state:
            self.push_message(f"Level finished: {self.level.end_state}. Press R to restart.")
            return

        previous_turn = self.level.turn_count
        previous_waves = self.level.spawned_waves
        self.level.run_turn()
        self.event_log.appendleft(f"Resolved turn {previous_turn + 1}.")
        result = f"Turn {self.level.turn_count} complete."

        if self.level.spawned_waves > previous_waves:
            wave_number = self.level.spawned_waves
            prefix = "Major wave!" if self.level.definition.is_major_wave(wave_number) else "Wave"
            self.show_banner(f"{prefix} {wave_number} has arrived")
            self.event_log.appendleft(f"Wave {wave_number} spawned.")

        if self.level.end_state == "Win":
            self.show_banner("Perimeter held")
            self.event_log.appendleft("All waves cleared.")
            result = "You win."
        elif self.level.end_state == "Loss":
            self.show_banner("The monsters breached the gate")
            self.event_log.appendleft("A monster breached the gate.")
            result = "You lose."
        else:
            self.push_message(f"Turn {self.level.turn_count} complete.")
        self.log_trajectory(trigger="next", command="next", result=result)

    def log_trajectory(self, trigger: str, command: str | None, result: str):
        if self.trajectory_logger is None:
            return
        self.trajectory_logger.log_board_snapshot(
            self.level,
            trigger=trigger,
            command=command,
            result=result,
        )

    def push_message(self, message: str):
        self.last_message = message
        self.message_until = time.time() + MESSAGE_DURATION

    def show_banner(self, text: str):
        self.banner_text = text
        self.banner_until = time.time() + BANNER_DURATION
        self.push_message(text)

    def display_name(self, defense_cls) -> str:
        return display_name_for(defense_cls.__name__)

    def draw(self):
        now = time.time()
        self.draw_background(now)
        self.draw_hud()
        self.draw_loadout_tray(now)
        self.draw_board_frame()
        self.draw_tiles()
        self.draw_entities(now)
        self.draw_sidebar()
        self.draw_message_bar(now)
        self.draw_banner(now)
        if self.level.end_state:
            self.draw_end_overlay()

    def draw_background(self, now: float):
        for y in range(SCREEN_HEIGHT):
            blend = y / SCREEN_HEIGHT
            if blend < 0.44:
                color = self.lerp_color((82, 95, 108), (124, 136, 148), blend / 0.44)
            else:
                color = self.lerp_color((78, 84, 90), (42, 45, 49), (blend - 0.44) / 0.56)
            pygame.draw.line(self.screen, color, (0, y), (SCREEN_WIDTH, y))

        for offset in range(-SCREEN_HEIGHT, SCREEN_WIDTH, 58):
            start = (offset, 0)
            end = (offset + SCREEN_HEIGHT, SCREEN_HEIGHT)
            pygame.draw.line(self.screen, (255, 255, 255, 10), start, end, 2)

        beacon_x = SCREEN_WIDTH - 132 + int(math.sin(now * 0.35) * 16)
        beacon_y = 88 + int(math.cos(now * 0.25) * 10)
        halo = pygame.Surface((180, 180), pygame.SRCALPHA)
        pygame.draw.circle(halo, (255, 194, 88, 18), (90, 90), 80)
        pygame.draw.circle(halo, (255, 222, 160, 36), (90, 90), 56)
        self.screen.blit(halo, (beacon_x - 90, beacon_y - 90))
        pygame.draw.circle(self.screen, (255, 197, 86), (beacon_x, beacon_y), 38)
        pygame.draw.circle(self.screen, (255, 236, 206), (beacon_x, beacon_y), 22)
        pygame.draw.circle(self.screen, (196, 126, 36), (beacon_x, beacon_y), 56, 3)
        for index in range(10):
            angle = (index / 10.0) * math.tau - now * 0.18
            start = (beacon_x + math.cos(angle) * 48, beacon_y + math.sin(angle) * 48)
            end = (beacon_x + math.cos(angle) * 66, beacon_y + math.sin(angle) * 66)
            pygame.draw.line(self.screen, (255, 214, 132), start, end, 3)

        self.draw_cloud((122, 72), 0.84)
        self.draw_cloud((354, 62), 0.66)
        self.draw_cloud((1020, 58), 0.74)

    def draw_cloud(self, position: tuple[int, int], scale: float):
        x, y = position
        cloud = pygame.Surface((260, 110), pygame.SRCALPHA)
        tint = (198, 205, 214, 110)
        for ellipse in ((10, 36, 84, 42), (60, 16, 94, 58), (122, 10, 92, 60), (178, 26, 74, 44), (66, 42, 136, 42)):
            pygame.draw.ellipse(cloud, tint, ellipse)
        cloud = pygame.transform.smoothscale(cloud, (int(260 * scale), int(110 * scale)))
        self.screen.blit(cloud, position)

    def draw_board_frame(self):
        frame_rect = pygame.Rect(BOARD_LEFT - 22, BOARD_TOP - 22, self.board_width + 44, self.board_height + 44)
        shadow_rect = frame_rect.move(8, 10)
        pygame.draw.rect(self.screen, (10, 12, 16, 130), shadow_rect, border_radius=24)
        self.draw_rounded_rect(self.screen, frame_rect, (78, 84, 92), radius=24)
        inner_rect = frame_rect.inflate(-20, -20)
        self.draw_rounded_rect(self.screen, inner_rect, (37, 41, 47), radius=18)

        warning_rect = pygame.Rect(BOARD_LEFT - 48, BOARD_TOP - 10, 36, self.board_height + 20)
        pygame.draw.rect(self.screen, (26, 28, 31), warning_rect, border_radius=12)
        stripe_colors = ((240, 180, 66), (34, 36, 39))
        for index in range(9):
            stripe = pygame.Rect(warning_rect.x + 4, warning_rect.y + 10 + index * 62, warning_rect.width - 8, 28)
            pygame.draw.rect(self.screen, stripe_colors[index % 2], stripe, border_radius=8)

        spawn_tile = self.tile_rect(0, self.entry_col)
        plaque = pygame.Rect(spawn_tile.x + 10, frame_rect.y + 4, spawn_tile.width - 20, 20)
        self.draw_vertical_gradient(plaque, (96, 103, 112), (52, 57, 63), radius=8)
        pygame.draw.rect(self.screen, (224, 181, 82), plaque, 1, border_radius=8)
        label = self.tiny_font.render("ENTRY", True, (248, 236, 214))
        self.screen.blit(label, label.get_rect(center=plaque.center))

    def draw_tiles(self):
        for row in range(self.board_rows):
            for col in range(self.board_cols):
                rect = self.tile_rect(row, col)
                if col == self.entry_col:
                    lane_shade = 0.12 if row % 2 == 0 else 0.04
                    base = self.lerp_color((84, 88, 95), (58, 62, 68), lane_shade)
                    inner_color = self.lerp_color(base, (110, 116, 124), 0.16)
                else:
                    lane_shade = 0.08 if row % 2 == 0 else 0.0
                    col_shade = 0.07 if col % 2 == 0 else 0.0
                    base = self.lerp_color((92, 97, 104), (66, 70, 77), lane_shade + col_shade)
                    inner_color = self.lerp_color(base, (118, 124, 132), 0.18)
                self.draw_rounded_rect(self.screen, rect, base, radius=16)
                inner = rect.inflate(-6, -6)
                self.draw_rounded_rect(self.screen, inner, inner_color, radius=12)
                pygame.draw.line(self.screen, (34, 37, 42), (inner.x + 10, inner.y + 8), (inner.right - 10, inner.y + 8), 1)
                pygame.draw.line(self.screen, (138, 146, 154), (inner.x + 10, inner.bottom - 10), (inner.right - 10, inner.bottom - 10), 1)
                for rivet in (
                    (inner.x + 10, inner.y + 10),
                    (inner.right - 10, inner.y + 10),
                    (inner.x + 10, inner.bottom - 10),
                    (inner.right - 10, inner.bottom - 10),
                ):
                    pygame.draw.circle(self.screen, (56, 61, 68), rivet, 3)
                    pygame.draw.circle(self.screen, (130, 138, 146), rivet, 2)

                if self.hovered_tile == (row, col):
                    if not self.has_selected_tool():
                        overlay = (255, 255, 255, 34)
                    else:
                        valid, _ = self.hover_validity or (False, None)
                        overlay = (104, 192, 214, 74) if valid else (224, 102, 74, 82)
                    surface = pygame.Surface(rect.size, pygame.SRCALPHA)
                    pygame.draw.rect(surface, overlay, surface.get_rect(), border_radius=16)
                    self.screen.blit(surface, rect.topleft)

    def draw_entities(self, now: float):
        for row in range(self.level.board.rows):
            for col in range(self.level.board.cols):
                occupant = self.level.board.tiles[row][col].occupant
                if occupant is None:
                    continue

                key = self.sprite_key_for_occupant(occupant)
                image = self.images.get(key)
                if isinstance(occupant, Monster):
                    if getattr(occupant, "frozen_turns", 0) > 0:
                        image = self.frozen_images.get(key, image)
                    elif getattr(occupant, "chilled", False):
                        image = self.chilled_images.get(key, image)
                    elif isinstance(occupant, Gargoyle) and getattr(occupant, "awakened", False):
                        image = self.awakened_images.get(key, image)
                rect = self.tile_rect(row, col)

                if isinstance(occupant, Monster):
                    bob = int(math.sin(now * 3.1 + row * 0.7 + col * 0.45) * 2)
                    draw_x, draw_y = self.monster_draw_position(image, rect, bob)
                    opaque_rect = image.get_bounding_rect(min_alpha=1).move(draw_x, draw_y)
                    self.draw_monster_shadow(opaque_rect, rect)
                    self.draw_hp_bar(occupant, rect)
                    self.screen.blit(image, (draw_x, draw_y))
                else:
                    special_rect = self.special_indicator_rect(occupant, rect)
                    bob = int(math.sin(now * 3.1 + row * 0.7 + col * 0.45) * 2)
                    draw_x, draw_y = self.defense_draw_position(image, rect, bob, special_rect)
                    opaque_rect = image.get_bounding_rect(min_alpha=1).move(draw_x, draw_y)
                    self.draw_defense_shadow(opaque_rect, rect)
                    self.screen.blit(image, (draw_x, draw_y))
                    self.draw_hp_bar(occupant, rect)
                    self.draw_special_indicator(occupant, rect)

    def sprite_key_for_occupant(self, occupant) -> str:
        if isinstance(occupant, Crusher) and getattr(occupant, "turns_to_digest", 0) > 0:
            return "CrusherRecharging"
        if isinstance(occupant, Berserker) and getattr(occupant, "enraged", False):
            return "BerserkerEnraged"
        if isinstance(occupant, Leaper) and getattr(occupant, "has_vaulted", False):
            return "LeaperGrounded"
        return type(occupant).__name__

    def monster_draw_position(self, image: pygame.Surface, tile_rect: pygame.Rect, bob: int) -> tuple[int, int]:
        bounds = image.get_bounding_rect(min_alpha=1)
        if bounds.width == 0 or bounds.height == 0:
            return tile_rect.centerx - image.get_width() // 2, tile_rect.bottom - image.get_height()

        draw_x = tile_rect.centerx - bounds.width // 2 - bounds.x
        draw_y = tile_rect.bottom - MONSTER_BOUNDS_INSET_BOTTOM - bounds.height - bounds.y + bob

        opaque_rect = bounds.move(draw_x, draw_y)
        min_left = tile_rect.x + MONSTER_BOUNDS_INSET_X
        max_right = tile_rect.right - MONSTER_BOUNDS_INSET_X
        min_top = tile_rect.y + MONSTER_BOUNDS_INSET_TOP
        max_bottom = tile_rect.bottom - MONSTER_BOUNDS_INSET_BOTTOM

        if opaque_rect.left < min_left:
            draw_x += min_left - opaque_rect.left
            opaque_rect.left = min_left
        if opaque_rect.right > max_right:
            draw_x -= opaque_rect.right - max_right
            opaque_rect.right = max_right
        if opaque_rect.top < min_top:
            draw_y += min_top - opaque_rect.top
            opaque_rect.top = min_top
        if opaque_rect.bottom > max_bottom:
            draw_y -= opaque_rect.bottom - max_bottom

        return draw_x, draw_y

    def draw_monster_shadow(self, opaque_rect: pygame.Rect, tile_rect: pygame.Rect):
        shadow_width = max(24, min(tile_rect.width - 18, int(opaque_rect.width * 0.82)))
        shadow_rect = pygame.Rect(0, 0, shadow_width, MONSTER_SHADOW_HEIGHT)
        shadow_rect.centerx = opaque_rect.centerx
        shadow_rect.bottom = tile_rect.bottom - MONSTER_SHADOW_BOTTOM_INSET
        shadow_rect.clamp_ip(tile_rect.inflate(-8, 0))
        pygame.draw.ellipse(self.screen, (24, 24, 24, 70), shadow_rect)

    def defense_draw_position(
        self,
        image: pygame.Surface,
        tile_rect: pygame.Rect,
        bob: int,
        special_rect: pygame.Rect | None,
    ) -> tuple[int, int]:
        bounds = image.get_bounding_rect(min_alpha=1)
        if bounds.width == 0 or bounds.height == 0:
            return tile_rect.centerx - image.get_width() // 2, tile_rect.bottom - image.get_height()

        draw_x = tile_rect.centerx - bounds.width // 2 - bounds.x
        draw_y = tile_rect.bottom - DEFENSE_BOUNDS_INSET_BOTTOM - bounds.height - bounds.y + bob

        opaque_rect = bounds.move(draw_x, draw_y)
        min_left = tile_rect.x + DEFENSE_BOUNDS_INSET_X
        max_right = tile_rect.right - DEFENSE_BOUNDS_INSET_X
        min_top = tile_rect.y + DEFENSE_BOUNDS_INSET_TOP
        max_bottom = tile_rect.bottom - DEFENSE_BOUNDS_INSET_BOTTOM

        if opaque_rect.left < min_left:
            draw_x += min_left - opaque_rect.left
            opaque_rect.left = min_left
        if opaque_rect.right > max_right:
            draw_x -= opaque_rect.right - max_right
            opaque_rect.right = max_right
        if opaque_rect.top < min_top:
            draw_y += min_top - opaque_rect.top
            opaque_rect.top = min_top
        if opaque_rect.bottom > max_bottom:
            draw_y -= opaque_rect.bottom - max_bottom
            opaque_rect.bottom = max_bottom

        if special_rect is not None and opaque_rect.colliderect(special_rect.inflate(DEFENSE_SPECIAL_BADGE_GAP * 2, DEFENSE_SPECIAL_BADGE_GAP * 2)):
            target_right = special_rect.left - DEFENSE_SPECIAL_BADGE_GAP
            if opaque_rect.right > target_right:
                shift = opaque_rect.right - target_right
                draw_x -= shift
                opaque_rect = bounds.move(draw_x, draw_y)
                if opaque_rect.left < min_left:
                    draw_x += min_left - opaque_rect.left

        return draw_x, draw_y

    def draw_defense_shadow(self, opaque_rect: pygame.Rect, tile_rect: pygame.Rect):
        shadow_width = max(22, min(tile_rect.width - 24, int(opaque_rect.width * 0.72)))
        shadow_rect = pygame.Rect(0, 0, shadow_width, DEFENSE_SHADOW_HEIGHT)
        shadow_rect.centerx = opaque_rect.centerx
        shadow_rect.bottom = tile_rect.bottom - DEFENSE_SHADOW_BOTTOM_INSET
        shadow_rect.clamp_ip(tile_rect.inflate(-10, 0))
        pygame.draw.ellipse(self.screen, (24, 24, 24, 58), shadow_rect)

    def draw_hp_bar(self, occupant, tile_rect: pygame.Rect):
        max_hp = self.base_hp.get(type(occupant), max(1, occupant.hp))
        ratio = max(0.0, min(1.0, occupant.hp / max_hp))
        width = tile_rect.width - 20
        bar_rect = pygame.Rect(tile_rect.x + 10, tile_rect.y + 10, width, 8)
        pygame.draw.rect(self.screen, (24, 40, 21), bar_rect, border_radius=6)
        fill_width = max(0, int(width * ratio))
        if fill_width > 0:
            if ratio > 0.65:
                color = (114, 219, 104)
            elif ratio > 0.35:
                color = (245, 204, 92)
            else:
                color = (229, 98, 92)
            fill_rect = pygame.Rect(bar_rect.x, bar_rect.y, fill_width, bar_rect.height)
            pygame.draw.rect(self.screen, color, fill_rect, border_radius=6)

    def special_indicator_rect(self, occupant, tile_rect: pygame.Rect) -> pygame.Rect | None:
        if not isinstance(occupant, (PowerPlant, LandMine, FreezeMine, Crusher, Cannon)):
            return None
        return pygame.Rect(
            tile_rect.right - DEFENSE_SPECIAL_BADGE_MARGIN - DEFENSE_SPECIAL_BADGE_WIDTH,
            tile_rect.bottom - DEFENSE_SPECIAL_BADGE_MARGIN - DEFENSE_SPECIAL_BADGE_HEIGHT,
            DEFENSE_SPECIAL_BADGE_WIDTH,
            DEFENSE_SPECIAL_BADGE_HEIGHT,
        )

    def draw_special_indicator(self, occupant, tile_rect: pygame.Rect):
        rect = self.special_indicator_rect(occupant, tile_rect)
        if rect is None:
            return

        if isinstance(occupant, PowerPlant):
            label = str(occupant.turns_to_generate)
            fill = (229, 183, 52, 220)
            text_color = (72, 48, 12)
        elif isinstance(occupant, Cannon):
            label = "!" if occupant.ready_to_fire else "R"
            fill = (92, 168, 88, 220) if occupant.ready_to_fire else (112, 126, 81, 220)
            text_color = (244, 241, 230)
        elif isinstance(occupant, Crusher):
            label = str(occupant.turns_to_digest) if occupant.turns_to_digest > 0 else "!"
            fill = (139, 83, 168, 220) if occupant.turns_to_digest > 0 else (92, 168, 88, 220)
            text_color = (244, 241, 230)
        elif isinstance(occupant, FreezeMine):
            label = "F"
            fill = (112, 186, 221, 220)
            text_color = (19, 41, 56)
        else:
            label = "A" if occupant.turns_to_arm <= 0 else str(occupant.turns_to_arm)
            fill = (116, 97, 62, 220) if occupant.turns_to_arm > 0 else (92, 168, 88, 220)
            text_color = (244, 241, 230)

        badge = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(badge, fill, badge.get_rect(), border_radius=8)
        pygame.draw.rect(badge, (255, 255, 255, 42), badge.get_rect(), 1, border_radius=8)
        text = self.tiny_font.render(label, True, text_color)
        badge.blit(text, text.get_rect(center=badge.get_rect().center))
        self.screen.blit(badge, rect.topleft)

    def draw_hud(self):
        panel = self.hud_rect
        self.draw_glass_panel(panel, (24, 30, 36, 182), outline=(176, 185, 196, 52))

        title = self.title_font.render("Tower Defense", True, (250, 247, 238))
        subtitle = self.subtitle_font.render(self.level.definition.name, True, (228, 192, 108))
        self.screen.blit(title, (46, 24))
        self.screen.blit(subtitle, (48, 62))

        wave_number = min(self.level.spawned_waves + 1, self.level.definition.total_waves)
        wave_suffix = "MAJOR" if self.level.definition.is_major_wave(wave_number) else f"{wave_number}/{self.level.definition.total_waves}"
        stats = [
            ("Turn", str(self.level.turn_count)),
            ("Wave", wave_suffix),
            ("Spawned", f"{self.level.spawned_waves}/{self.level.definition.total_waves}"),
        ]

        card_width = 126
        gap = 12
        total_width = len(stats) * card_width + (len(stats) - 1) * gap
        start_x = panel.right - total_width - 18
        for index, (label, value) in enumerate(stats):
            card = pygame.Rect(start_x + index * (card_width + gap), 26, card_width, 62)
            self.draw_glass_panel(card, (86, 96, 108, 64), outline=(196, 164, 96, 44))
            label_surface = self.small_font.render(label.upper(), True, (208, 214, 220))
            value_surface = self.hud_font.render(value, True, (248, 242, 228))
            self.screen.blit(label_surface, (card.x + 12, card.y + 8))
            self.screen.blit(value_surface, (card.x + 12, card.y + 28))

    def draw_loadout_tray(self, now: float):
        panel = self.loadout_tray_rect
        shadow_rect = panel.move(0, 6)
        pygame.draw.rect(self.screen, (0, 0, 0, 72), shadow_rect, border_radius=22)
        self.draw_vertical_gradient(panel, (106, 114, 124), (56, 61, 69), radius=22)
        pygame.draw.rect(self.screen, (31, 34, 40), panel, 3, border_radius=22)

        inner_rect = panel.inflate(-10, -10)
        self.draw_vertical_gradient(inner_rect, (72, 77, 85), (40, 44, 50), radius=16)
        pygame.draw.rect(self.screen, (164, 172, 180), inner_rect, 1, border_radius=16)

        self.draw_energy_bank()

        for index, defense_cls in enumerate(self.level.definition.defense_roster):
            self.draw_loadout_card(index, defense_cls, now)

        self.draw_clear_slot()

        if self.selected_defense_cls is not None:
            selected_index = self.level.definition.defense_roster.index(self.selected_defense_cls)
            self.draw_selection_marker(self.card_rect(selected_index))
        elif self.clear_selected:
            self.draw_selection_marker(self.clear_rect.inflate(-8, -8))

    def draw_energy_bank(self):
        self.draw_vertical_gradient(self.energy_bank_rect, (112, 118, 126), (58, 63, 71), radius=16)
        pygame.draw.rect(self.screen, (28, 31, 36), self.energy_bank_rect, 2, border_radius=16)

        inner_rect = self.energy_bank_rect.inflate(-8, -8)
        self.draw_vertical_gradient(inner_rect, (58, 63, 72), (34, 38, 44), radius=12)
        pygame.draw.rect(self.screen, (234, 180, 84), inner_rect, 1, border_radius=12)

        energy_image = self.images.get("Energy")
        if energy_image is not None:
            icon_rect = energy_image.get_rect(center=(inner_rect.centerx, inner_rect.y + 19))
            self.screen.blit(energy_image, icon_rect)
        else:
            orb_center = (inner_rect.centerx, inner_rect.y + 18)
            pygame.draw.circle(self.screen, (255, 241, 154), orb_center, 17)
            pygame.draw.circle(self.screen, (255, 253, 208), orb_center, 12)
            for index in range(12):
                angle = index * (math.tau / 12)
                start = (orb_center[0] + math.cos(angle) * 15, orb_center[1] + math.sin(angle) * 15)
                end = (orb_center[0] + math.cos(angle) * 22, orb_center[1] + math.sin(angle) * 22)
                pygame.draw.line(self.screen, (255, 228, 102), start, end, 2)

        plaque_rect = pygame.Rect(inner_rect.x + 10, inner_rect.bottom - 24, inner_rect.width - 20, 18)
        self.draw_vertical_gradient(plaque_rect, (234, 186, 92), (176, 122, 42), radius=8)
        pygame.draw.rect(self.screen, (88, 55, 20), plaque_rect, 1, border_radius=8)
        value_surface = self.hud_font.render(str(self.level.energy), True, (34, 24, 12))
        self.screen.blit(value_surface, value_surface.get_rect(center=plaque_rect.center))

    def draw_clear_slot(self):
        rect = self.clear_rect
        self.draw_vertical_gradient(rect, (112, 118, 126), (58, 63, 71), radius=16)
        border_color = (255, 208, 110) if self.clear_selected else (28, 31, 36)
        border_width = 3 if self.clear_selected else 2
        pygame.draw.rect(self.screen, border_color, rect, border_width, border_radius=16)

        inner = rect.inflate(-8, -8)
        self.draw_vertical_gradient(inner, (74, 79, 87), (42, 46, 52), radius=12)
        pygame.draw.rect(self.screen, (160, 169, 178), inner, 1, border_radius=12)
        self.draw_clear_icon(inner)

        hotkey = self.small_font.render("S", True, (246, 235, 216))
        self.screen.blit(hotkey, (rect.right - 18, rect.y + 8))

    def draw_clear_icon(self, rect: pygame.Rect):
        center = rect.center
        radius = min(rect.width, rect.height) // 2 - 10
        shadow_center = (center[0] + 2, center[1] + 2)

        pygame.draw.circle(self.screen, (34, 20, 22), shadow_center, radius + 2)
        pygame.draw.circle(self.screen, (248, 246, 240), center, radius)
        pygame.draw.circle(self.screen, (170, 28, 36), center, radius, 6)

        slash_start = (center[0] - radius + 8, center[1] + radius - 8)
        slash_end = (center[0] + radius - 8, center[1] - radius + 8)
        pygame.draw.line(self.screen, (112, 14, 24), slash_start, slash_end, 10)
        pygame.draw.line(self.screen, (224, 53, 69), slash_start, slash_end, 6)

    def draw_selection_marker(self, rect: pygame.Rect):
        marker = [
            (rect.centerx - 10, rect.y - 8),
            (rect.centerx + 10, rect.y - 8),
            (rect.centerx, rect.y + 4),
        ]
        pygame.draw.polygon(self.screen, (255, 224, 74), marker)
        pygame.draw.polygon(self.screen, (122, 89, 19), marker, 1)

    def draw_sidebar(self):
        panel = self.info_panel_rect
        self.draw_glass_panel(panel, (24, 29, 34, 172), outline=(171, 180, 191, 28))

        if self.replay_mode:
            title = self.hud_font.render("Replay", True, (246, 240, 226))
            hint = self.small_font.render("Space pause. Left/Right step. R replay.", True, (198, 205, 214))
        else:
            title = self.hud_font.render("Control Panel", True, (246, 240, 226))
            hotkey_max = max(1, len(self.level.definition.defense_roster))
            hint = self.small_font.render(
                f"Hotkeys 1-{hotkey_max} deploy. S clears. Space resolves. R restarts.",
                True,
                (198, 205, 214),
            )
        self.screen.blit(title, (self.sidebar_left + 18, self.sidebar_top + 16))
        self.screen.blit(hint, (self.sidebar_left + 18, self.sidebar_top + 48))

        info_top = self.sidebar_top + 78
        if self.replay_mode:
            info_bottom = self.sidebar_bottom - 18
        else:
            info_bottom = self.end_turn_button.rect.top - 14
        info_rect = pygame.Rect(self.sidebar_left + 18, info_top, self.sidebar_width - 36, max(84, info_bottom - info_top))
        self.draw_glass_panel(info_rect, (72, 78, 86, 34), outline=(255, 255, 255, 14))
        if self.replay_mode:
            self.draw_replay_info(info_rect)
        else:
            self.draw_hover_info(info_rect)
            self.draw_button(self.end_turn_button, active=not self.level.end_state)
            self.draw_button(self.restart_button, active=True)

    def draw_replay_info(self, rect: pygame.Rect):
        current_frame = self.replay_frames[self.replay_index]
        if self.follow_replay_log:
            if self.replay_paused:
                status = "Paused"
            elif self.replay_index + 1 >= len(self.replay_frames):
                status = "Following"
            else:
                status = "Catching up"
        else:
            status = "Finished" if self.replay_finished else ("Paused" if self.replay_paused else "Playing")
        lines = [
            f"State {self.replay_index + 1} of {len(self.replay_frames)}",
            f"Status: {status}",
            f"Delay: {self.replay_delay:.2f}s per state",
        ]
        if self.follow_replay_log:
            lines.append(f"Source: {self.replay_log_path.name}")
        if current_frame.command:
            lines.append(f"Action: {current_frame.command}")
        else:
            lines.append("Action: initial board state")
        result = current_frame.result.strip()
        if result:
            lines.append(result.splitlines()[0])

        header = self.small_font.render("Replay State", True, (244, 239, 229))
        self.screen.blit(header, (rect.x + 14, rect.y + 12))
        y = rect.y + 44
        text_bottom = rect.bottom - 12
        for line in lines:
            for wrapped in textwrap.wrap(line, width=34)[:3]:
                if y + 20 > text_bottom:
                    return
                surface = self.small_font.render(wrapped, True, (198, 205, 214))
                self.screen.blit(surface, (rect.x + 14, y))
                y += 24

    def draw_loadout_card(self, index: int, defense_cls, now: float):
        rect = self.card_rect(index)
        is_selected = defense_cls is self.selected_defense_cls
        cooldown = self.level.deploy_client.cooldowns.get(defense_cls, 0)
        affordable = self.level.energy >= defense_cls.cost
        can_deploy = cooldown == 0 and affordable and not self.level.end_state
        primary, secondary = CARD_COLORS[defense_cls]
        layout = self.loadout_card_layout(rect)
        art_rect = layout["art_rect"]
        cost_plate = layout["cost_plate"]
        status_bubble = layout["status_bubble"]

        self.validate_loadout_card_layout(rect, layout)

        shadow_rect = rect.move(0, LOADOUT_CARD_SHADOW_DEPTH)
        pygame.draw.rect(self.screen, (0, 0, 0, 70), shadow_rect, border_radius=16)
        frame_top = self.lerp_color(primary, (198, 204, 212), 0.52)
        frame_bottom = self.lerp_color(secondary, (86, 92, 100), 0.36)
        self.draw_vertical_gradient(rect, frame_top, frame_bottom, radius=10)
        border_color = (238, 186, 92) if is_selected else (44, 48, 55)
        border_width = 3 if is_selected else 2
        pygame.draw.rect(self.screen, border_color, rect, border_width, border_radius=10)

        self.draw_vertical_gradient(
            art_rect,
            self.lerp_color(primary, (152, 161, 170), 0.26),
            self.lerp_color(secondary, (76, 83, 90), 0.22),
            radius=8,
        )
        pygame.draw.rect(self.screen, (42, 46, 52), art_rect, 1, border_radius=8)

        icon_key = defense_cls.__name__
        icon = self.scale_to_fit(self.images[icon_key], art_rect.inflate(-CARD_CONTENT_PADDING * 2, -CARD_CONTENT_PADDING * 2).size)
        icon_x = art_rect.centerx - icon.get_width() // 2
        icon_y = art_rect.centery - icon.get_height() // 2 + int(math.sin(now * 2.4 + index) * 1.5)
        self.screen.blit(icon, (icon_x, icon_y))

        self.draw_vertical_gradient(cost_plate, (228, 184, 94), (168, 118, 44), radius=6)
        pygame.draw.rect(self.screen, (88, 56, 23), cost_plate, 1, border_radius=6)
        cost = self.packet_cost_font.render(str(defense_cls.cost), True, (34, 24, 12))
        self.screen.blit(cost, cost.get_rect(center=cost_plate.center))

        if not can_deploy:
            overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
            overlay.fill((18, 20, 18, 95 if cooldown else 66))
            self.screen.blit(overlay, rect.topleft)
            if cooldown > 0:
                fraction = cooldown / max(1, defense_cls.cooldown)
                cover_height = int(rect.height * fraction)
                recharge = pygame.Surface((rect.width, cover_height), pygame.SRCALPHA)
                recharge.fill((23, 28, 24, 150))
                self.screen.blit(recharge, (rect.x, rect.y))

        if cooldown > 0:
            pygame.draw.ellipse(self.screen, (214, 220, 226), status_bubble)
            pygame.draw.ellipse(self.screen, (89, 96, 104), status_bubble, 1)
            status_text = self.packet_bubble_font.render(str(cooldown), True, (37, 41, 46))
            status_text_rect = status_text.get_rect(center=status_bubble.center)
            self.screen.blit(status_text, status_text_rect)

    def loadout_card_layout(self, rect: pygame.Rect) -> dict[str, pygame.Rect]:
        inner = pygame.Rect(
            rect.x + CARD_INSET_X,
            rect.y + CARD_INSET_Y,
            rect.width - CARD_INSET_X * 2,
            rect.height - CARD_INSET_Y * 2,
        )
        cost_plate = pygame.Rect(
            inner.x + 7,
            inner.bottom - CARD_COST_HEIGHT,
            inner.width - 14,
            CARD_COST_HEIGHT,
        )
        art_rect = pygame.Rect(
            inner.x,
            inner.y,
            inner.width,
            cost_plate.top - inner.y - CARD_PANEL_BOTTOM_GAP,
        )
        status_bubble = pygame.Rect(
            art_rect.x + CARD_STATUS_MARGIN,
            art_rect.y + CARD_STATUS_MARGIN,
            CARD_STATUS_SIZE,
            CARD_STATUS_SIZE,
        )
        return {
            "inner": inner,
            "art_rect": art_rect,
            "cost_plate": cost_plate,
            "status_bubble": status_bubble,
        }

    def validate_loadout_card_layout(self, rect: pygame.Rect, layout: dict[str, pygame.Rect]):
        inner = layout["inner"]
        art_rect = layout["art_rect"]
        cost_plate = layout["cost_plate"]
        status_bubble = layout["status_bubble"]

        assert rect.contains(inner)
        assert inner.contains(art_rect)
        assert inner.contains(cost_plate)
        assert art_rect.contains(status_bubble)
        assert art_rect.width > 0 and art_rect.height > 0
        assert not status_bubble.colliderect(cost_plate)

    def draw_hover_info(self, rect: pygame.Rect):
        lines = []
        if self.hovered_tile is not None:
            row, col = self.hovered_tile
            occupant = self.level.board.tiles[row][col].occupant
            lines.append(f"Tile {row + 1}, {col + 1}")
            if occupant is None:
                if col == self.entry_col:
                    lines.append("Monster entry column.")
                else:
                    lines.append("Empty tile.")
                if self.clear_selected:
                    valid, reason = self.hover_validity or (False, None)
                    if valid:
                        lines.append("Remove tool can clear a defense here.")
                    else:
                        lines.append(f"Cannot clear: {CLEAR_FAILURE_MESSAGES.get(reason, reason)}.")
                elif self.selected_defense_cls is not None:
                    valid, reason = self.hover_validity or (False, None)
                    if valid:
                        lines.append(f"Can deploy {self.display_name(self.selected_defense_cls)} here.")
                    else:
                        lines.append(f"Cannot deploy: {self.display_placement_reason(reason)}.")
            else:
                lines.append(f"{self.display_name(type(occupant))} with {occupant.hp} HP.")
                special = format_special_state(type(occupant).__name__, occupant.special_state())
                if special:
                    lines.append(special + ".")
                if self.clear_selected:
                    valid, reason = self.hover_validity or (False, None)
                    if valid:
                        lines.append("Click to clear this defense.")
                    else:
                        lines.append(f"Cannot clear: {CLEAR_FAILURE_MESSAGES.get(reason, reason)}.")
        elif self.selected_defense_cls is not None:
            defense_cls = self.selected_defense_cls
            lines.append(self.display_name(defense_cls))
            lines.append(f"Cost: {defense_cls.cost} {RESOURCE_LABEL}.")
            lines.append(f"Cooldown: {defense_cls.cooldown} turns.")
            lines.append("Pick a tile on the grid.")
        elif self.clear_selected:
            lines.append("Remove tool selected.")
            lines.append("Click one of your defenses to clear it.")
            lines.append("The remove tool cannot affect monsters.")
        else:
            lines.extend([
                "Select a defense card or remove tool to preview an action.",
                "Click End Turn after setting your board.",
            ])

        header = self.small_font.render("Tile / Action", True, (244, 239, 229))
        self.screen.blit(header, (rect.x + 14, rect.y + 12))
        y = rect.y + 44
        text_bottom = rect.bottom - 12
        for line in lines[:5]:
            for wrapped in textwrap.wrap(line, width=34)[:2]:
                if y + 20 > text_bottom:
                    return
                surface = self.small_font.render(wrapped, True, (198, 205, 214))
                self.screen.blit(surface, (rect.x + 14, y))
                y += 24

        if self.event_log:
            y += 8
            if y + 18 > text_bottom:
                return
            log_header = self.small_font.render("Recent", True, (244, 239, 229))
            self.screen.blit(log_header, (rect.x + 14, y))
            y += 26
            for entry in list(self.event_log)[:3]:
                if y + 16 > text_bottom:
                    return
                surface = self.tiny_font.render(entry, True, (190, 199, 208))
                self.screen.blit(surface, (rect.x + 14, y))
                y += 20

    def draw_button(self, button: Button, active: bool):
        mouse_over = button.rect.collidepoint(pygame.mouse.get_pos())
        if active:
            top, bottom = ((102, 128, 134), (56, 72, 79)) if button.label == "End Turn" else ((201, 145, 72), (122, 78, 31))
        else:
            top, bottom = (86, 90, 96), (50, 54, 60)
        if mouse_over and active:
            top = self.lerp_color(top, (255, 255, 255), 0.08)
        self.draw_vertical_gradient(button.rect, top, bottom, radius=16)
        pygame.draw.rect(self.screen, (255, 255, 255, 28), button.rect, 2, border_radius=16)
        label = self.body_font.render(button.label, True, (250, 246, 237))
        self.screen.blit(label, label.get_rect(center=button.rect.center))

    def draw_message_bar(self, now: float):
        rect = pygame.Rect(28, SCREEN_HEIGHT - 46, SCREEN_WIDTH - 56, 28)
        self.draw_glass_panel(rect, (22, 28, 34, 176), outline=(166, 176, 186, 18))
        color = (243, 237, 216) if now < self.message_until else (188, 196, 204)
        surface = self.small_font.render(self.last_message, True, color)
        self.screen.blit(surface, (rect.x + 12, rect.y + 5))

    def draw_banner(self, now: float):
        if not self.banner_text or now >= self.banner_until:
            return
        remaining = self.banner_until - now
        alpha = 255 if remaining > 0.45 else int(255 * remaining / 0.45)
        banner = pygame.Surface((self.board_width - 80, 72), pygame.SRCALPHA)
        pygame.draw.rect(banner, (24, 27, 31, max(0, alpha - 58)), banner.get_rect(), border_radius=18)
        pygame.draw.rect(banner, (240, 181, 78, max(0, alpha - 12)), banner.get_rect(), 3, border_radius=18)
        text = self.hud_font.render(self.banner_text, True, (250, 244, 230))
        banner.blit(text, text.get_rect(center=banner.get_rect().center))
        self.screen.blit(banner, (BOARD_LEFT + 40, BOARD_TOP + 18))

    def draw_end_overlay(self):
        overlay = pygame.Surface((self.board_width, self.board_height), pygame.SRCALPHA)
        overlay.fill((9, 12, 16, 158))
        self.screen.blit(overlay, (BOARD_LEFT, BOARD_TOP))
        title = "You Win" if self.level.end_state == "Win" else "You Lose"
        subtitle = "Press R to restart the level"
        title_surface = self.title_font.render(title, True, (255, 246, 224))
        subtitle_surface = self.body_font.render(subtitle, True, (212, 219, 226))
        center_x = BOARD_LEFT + self.board_width // 2
        center_y = BOARD_TOP + self.board_height // 2
        self.screen.blit(title_surface, title_surface.get_rect(center=(center_x, center_y - 18)))
        self.screen.blit(subtitle_surface, subtitle_surface.get_rect(center=(center_x, center_y + 28)))

    def tile_rect(self, row: int, col: int) -> pygame.Rect:
        return pygame.Rect(
            BOARD_LEFT + col * TILE_WIDTH,
            BOARD_TOP + row * TILE_HEIGHT,
            TILE_WIDTH,
            TILE_HEIGHT,
        )

    def card_rect(self, index: int) -> pygame.Rect:
        return pygame.Rect(
            self.loadout_card_left + index * (self.loadout_card_width + CARD_GAP),
            self.loadout_card_top,
            self.loadout_card_width,
            self.loadout_card_height,
        )

    def tile_at_pos(self, pos: tuple[int, int]):
        x, y = pos
        if not (BOARD_LEFT <= x < BOARD_LEFT + self.board_width and BOARD_TOP <= y < BOARD_TOP + self.board_height):
            return None
        col = (x - BOARD_LEFT) // TILE_WIDTH
        row = (y - BOARD_TOP) // TILE_HEIGHT
        if 0 <= row < self.level.board.rows and 0 <= col < self.level.board.cols:
            return int(row), int(col)
        return None

    def draw_glass_panel(self, rect: pygame.Rect, fill_rgba, outline=(255, 255, 255, 30)):
        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(surface, fill_rgba, surface.get_rect(), border_radius=20)
        highlight = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(highlight, (210, 219, 228, 18), (3, 3, rect.width - 6, rect.height // 2), border_radius=18)
        surface.blit(highlight, (0, 0))
        self.screen.blit(surface, rect.topleft)
        pygame.draw.rect(self.screen, outline, rect, 1, border_radius=20)

    def draw_vertical_gradient(self, rect: pygame.Rect, top_color, bottom_color, radius: int):
        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        for y in range(rect.height):
            blend = y / max(1, rect.height - 1)
            color = self.lerp_color(top_color, bottom_color, blend)
            pygame.draw.line(surface, color, (0, y), (rect.width, y))
        mask = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
        surface.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self.screen.blit(surface, rect.topleft)

    def draw_rounded_rect(self, surface: pygame.Surface, rect: pygame.Rect, color, radius: int):
        pygame.draw.rect(surface, color, rect, border_radius=radius)

    def lerp_color(self, start, end, blend: float):
        blend = max(0.0, min(1.0, blend))
        return (
            int(start[0] + (end[0] - start[0]) * blend),
            int(start[1] + (end[1] - start[1]) * blend),
            int(start[2] + (end[2] - start[2]) * blend),
        )


def build_level_from_seed(seed: int | None, level_id: int):
    def factory():
        level = build_demo_level(level_id=level_id)
        if seed is None:
            return level
        return level.definition.create_level(rng_seed=seed)

    return factory


def load_replay_frames(log_path: Path) -> list[ReplayFrame]:
    frames = []
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("event") != "board_snapshot":
                continue
            snapshot = record.get("snapshot")
            if not isinstance(snapshot, dict):
                continue
            frames.append(
                ReplayFrame(
                    index=len(frames),
                    trigger=str(record.get("trigger") or "unknown"),
                    command=record.get("command"),
                    result=str(record.get("result") or ""),
                    snapshot=snapshot,
                )
            )
    if not frames:
        raise SystemExit(f"No structured board snapshots found in {log_path}. Replay requires a JSONL log with board_snapshot events.")
    return frames


def main():
    parser = argparse.ArgumentParser(description="Pretty pygame client for the turn-based tower defense benchmark.")
    parser.add_argument("--seed", type=int, default=7, help="Random seed for the demo level.")
    parser.add_argument("--level", type=int, default=1, help="Level number to load in live play.")
    parser.add_argument("--log-dir", type=Path, default=None, help="Directory for optional JSONL trajectory logs of your manual run.")
    parser.add_argument("--replay-log", type=Path, default=None, help="Replay a saved Responses run log in the pygame visualizer.")
    parser.add_argument("--follow-replay-log", action="store_true", help="Keep polling the replay log for newly appended board snapshots.")
    parser.add_argument("--replay-delay", type=float, default=1.0, help="Seconds to show each replay state before advancing.")
    parser.add_argument("--smoke-test", action="store_true", help="Render a frame and exit.")
    parser.add_argument("--screenshot", type=Path, default=None, help="Optional screenshot path for smoke tests.")
    args = parser.parse_args()

    if args.replay_log is not None:
        replay_frames = load_replay_frames(args.replay_log)
        app = GameApp(
            replay_frames=replay_frames,
            replay_delay=args.replay_delay,
            replay_log_path=args.replay_log,
            follow_replay_log=args.follow_replay_log,
        )
    else:
        trajectory_logger = None
        if args.log_dir is not None:
            trajectory_logger = TrajectoryLogger(
                log_dir=args.log_dir,
                interface="pygame",
                seed=args.seed,
                level_id=args.level,
            )
            print(f"[trajectory log] {trajectory_logger.path}")
        app = GameApp(
            build_level_from_seed(args.seed, args.level),
            trajectory_logger=trajectory_logger,
        )
    if args.smoke_test:
        app.draw()
        if args.screenshot is not None:
            pygame.image.save(app.screen, str(args.screenshot))
        if app.trajectory_logger is not None:
            app.trajectory_logger.close(app.level)
        pygame.quit()
        return
    app.run()


if __name__ == "__main__":
    main()
