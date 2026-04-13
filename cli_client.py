from __future__ import annotations

import argparse
import contextlib
import io
import sys
from dataclasses import dataclass
from pathlib import Path

from game_server import available_level_ids, create_level
from trajectory_logging import TrajectoryLogger

CELL_WIDTH = 6

CLI_PROMPT = "td> "
RESOURCE_LABEL = "energy"
DEFENSE_LABEL = "defense"
MONSTER_LABEL = "monster"

DISPLAY_NAME_BY_CLASS = {
    "Turret": "Turret",
    "QuadTurret": "QuadTurret",
    "PowerPlant": "PowerPlant",
    "Barricade": "Barricade",
    "Grenade": "Grenade",
    "LandMine": "LandMine",
    "FreezeMine": "FreezeMine",
    "IceTurret": "IceTurret",
    "DoubleTurret": "DoubleTurret",
    "Crusher": "Crusher",
    "Backstabber": "Backstabber",
    "Cannon": "Cannon",
    "Vortex": "Vortex",
    "LineBomb": "LineBomb",
    "ForceWall": "ForceWall",
    "AcidSprayer": "AcidSprayer",
    "Skeleton": "Skeleton",
    "Imp": "Imp",
    "Goblin": "Goblin",
    "Orc": "Orc",
    "Herald": "Herald",
    "Leaper": "Leaper",
    "Necromancer": "Necromancer",
    "Berserker": "Berserker",
    "Gargoyle": "Gargoyle",
    "Golem": "Golem",
    "Juggernaut": "Juggernaut",
}

TOKEN_BY_NAME = {
    "Turret": "Tur",
    "QuadTurret": "Qdt",
    "PowerPlant": "Pwr",
    "Backstabber": "Bst",
    "IceTurret": "Ice",
    "Cannon": "Can",
    "Vortex": "Vor",
    "LineBomb": "Lin",
    "DoubleTurret": "Dbl",
    "Crusher": "Cru",
    "Barricade": "Bar",
    "ForceWall": "For",
    "AcidSprayer": "Acd",
    "Grenade": "Gre",
    "LandMine": "Mne",
    "FreezeMine": "Frz",
    "Skeleton": "Ske",
    "Herald": "Her",
    "Imp": "Imp",
    "Goblin": "Gob",
    "Orc": "Orc",
    "Leaper": "Lea",
    "Necromancer": "Nec",
    "Berserker": "Ber",
    "Gargoyle": "Gar",
    "Golem": "Gol",
    "Juggernaut": "Jug",
}

DEFENSE_ALIASES = {
    "tur": "Turret",
    "turret": "Turret",
    "qdt": "QuadTurret",
    "quad": "QuadTurret",
    "quadturret": "QuadTurret",
    "quad-turret": "QuadTurret",
    "quad turret": "QuadTurret",
    "pwr": "PowerPlant",
    "power": "PowerPlant",
    "powerplant": "PowerPlant",
    "power-plant": "PowerPlant",
    "power plant": "PowerPlant",
    "bst": "Backstabber",
    "back": "Backstabber",
    "backstabber": "Backstabber",
    "back-stabber": "Backstabber",
    "back stabber": "Backstabber",
    "ice": "IceTurret",
    "iceturret": "IceTurret",
    "ice-turret": "IceTurret",
    "ice turret": "IceTurret",
    "can": "Cannon",
    "cannon": "Cannon",
    "vor": "Vortex",
    "vortex": "Vortex",
    "lin": "LineBomb",
    "line": "LineBomb",
    "linebomb": "LineBomb",
    "line-bomb": "LineBomb",
    "line bomb": "LineBomb",
    "dbl": "DoubleTurret",
    "double": "DoubleTurret",
    "doubleturret": "DoubleTurret",
    "double-turret": "DoubleTurret",
    "double turret": "DoubleTurret",
    "cru": "Crusher",
    "crusher": "Crusher",
    "crush": "Crusher",
    "bar": "Barricade",
    "barricade": "Barricade",
    "barric": "Barricade",
    "for": "ForceWall",
    "force": "ForceWall",
    "forcewall": "ForceWall",
    "force-wall": "ForceWall",
    "force wall": "ForceWall",
    "acd": "AcidSprayer",
    "acid": "AcidSprayer",
    "sprayer": "AcidSprayer",
    "acidsprayer": "AcidSprayer",
    "acid-sprayer": "AcidSprayer",
    "acid sprayer": "AcidSprayer",
    "gre": "Grenade",
    "gren": "Grenade",
    "grenade": "Grenade",
    "mne": "LandMine",
    "mine": "LandMine",
    "landmine": "LandMine",
    "land-mine": "LandMine",
    "land mine": "LandMine",
    "frz": "FreezeMine",
    "freezemine": "FreezeMine",
    "freeze-mine": "FreezeMine",
    "freeze mine": "FreezeMine",
}

GUIDE_ALIASES = {
    **DEFENSE_ALIASES,
    "ske": "Skeleton",
    "skeleton": "Skeleton",
    "her": "Herald",
    "herald": "Herald",
    "imp": "Imp",
    "gob": "Goblin",
    "goblin": "Goblin",
    "orc": "Orc",
    "lea": "Leaper",
    "leaper": "Leaper",
    "leap": "Leaper",
    "nec": "Necromancer",
    "necro": "Necromancer",
    "necromancer": "Necromancer",
    "gar": "Gargoyle",
    "gargoyle": "Gargoyle",
    "gol": "Golem",
    "golem": "Golem",
    "ber": "Berserker",
    "berserker": "Berserker",
    "berserk": "Berserker",
    "jug": "Juggernaut",
    "juggernaut": "Juggernaut",
}

ROSTER_ALIASES = {
    "Turret": "tur",
    "QuadTurret": "qdt",
    "PowerPlant": "pwr",
    "Backstabber": "bst",
    "IceTurret": "ice",
    "Cannon": "can",
    "Vortex": "vor",
    "LineBomb": "lin",
    "DoubleTurret": "dbl",
    "Crusher": "cru",
    "Barricade": "bar",
    "ForceWall": "for",
    "AcidSprayer": "acd",
    "Grenade": "gre",
    "LandMine": "mne",
    "FreezeMine": "frz",
    "Skeleton": "ske",
    "Herald": "her",
    "Imp": "imp",
    "Goblin": "gob",
    "Orc": "orc",
    "Leaper": "lea",
    "Necromancer": "nec",
    "Berserker": "ber",
    "Gargoyle": "gar",
    "Golem": "gol",
    "Juggernaut": "jug",
}

DEFENSE_DESCRIPTIONS = {
    "Turret": "tur: fires at the nearest monster ahead for 1 damage.",
    "QuadTurret": "qdt: hits the nearest monster on each diagonal for 2 damage.",
    "PowerPlant": "pwr: generates extra energy after a short delay, then every 4 turns.",
    "Backstabber": "bst: strikes the tile behind it for 8 damage.",
    "IceTurret": "ice: fires like a turret, but slows monsters so they only act every other turn.",
    "Cannon": "can: hits a lane target for 4, then splashes nearby monsters for 1 every other turn.",
    "Vortex": "vor: fires every turn at the tile exactly three spaces ahead and deals 6 damage to a monster standing there.",
    "LineBomb": "lin: clears an entire lane and is consumed.",
    "DoubleTurret": "dbl: fires twice for 2 total damage.",
    "Crusher": "cru: instantly crushes the monster directly ahead, then recharges for 8 turns.",
    "Barricade": "bar: a high-HP blocker.",
    "ForceWall": "for: a tougher blocker that strips a leaper's jump.",
    "AcidSprayer": "acd: hits all occupied tiles up to four spaces ahead.",
    "Grenade": "gre: explodes once in a 3x3 area and is consumed.",
    "LandMine": "mne: arms after a delay, then destroys the next adjacent monster.",
    "FreezeMine": "frz: starts armed and freezes the adjacent monster ahead for 4 turns, then is consumed.",
}

MONSTER_DESCRIPTIONS = {
    "Skeleton": "ske: basic monster.",
    "Herald": "her: marks a major wave.",
    "Imp": "imp: pokes the frontmost defense in its lane on turns when it does not move.",
    "Goblin": "gob: a sturdier frontliner.",
    "Orc": "orc: a very tough bruiser.",
    "Leaper": "lea: fast monster that jumps the first defense ahead and can break through the landing defense.",
    "Necromancer": "nec: slow monster that periodically summons skeletons into open neighboring cells.",
    "Gargoyle": "gar: passive while dormant, but turns into a fast charge attacker once damaged.",
    "Golem": "gol: a huge pusher that shoves defense chains left toward your base.",
    "Berserker": "ber: becomes much faster and stronger after it drops to half health.",
    "Juggernaut": "jug: a rolling behemoth that crushes everything in its path.",
}

DEPLOY_FAILURE_MESSAGES = {
    "entry column not deployable": "That column is reserved for monster entries.",
    "not enough energy": f"Not enough {RESOURCE_LABEL} for that defense.",
    "cooldown active": "That card is still recharging.",
    "tile occupied": "That tile is already occupied.",
}

CLEAR_FAILURE_MESSAGES = {
    "tile empty": "That tile is empty.",
    "cannot clear monsters": f"You can only clear {DEFENSE_LABEL}s.",
}

COMMAND_USAGE = {
    "show": "show",
    "deploy": "deploy <name> <row> <col>",
    "clear": "clear <row> <col>",
    "inspect": "inspect <row> <col>",
    "guide": "guide <abbr>",
    "next": "next",
    "status": "status",
    "help": "help",
    "instructions": "instructions",
    "level": "level <number>",
    "restart": "restart",
    "quit": "quit",
}

GUIDE_ENTRIES = {
    "Turret": [
        "Turret",
        "Type: defense",
        "Abbreviation: tur",
        "Cost: 4 energy",
        "HP: 1",
        "Recharge: 2 turns",
        "Role: baseline lane damage.",
        "Behavior: attacks before monsters move each turn and fires at the nearest monster ahead for 1 damage.",
        "Use: efficient early offense when you need simple repeated damage.",
    ],
    "QuadTurret": [
        "QuadTurret",
        "Type: defense",
        "Abbreviation: qdt",
        "Cost: 6 energy",
        "HP: 1",
        "Recharge: 2 turns",
        "Role: diagonal multi-lane coverage.",
        "Behavior: each turn it scans the four diagonal directions around itself and hits the nearest monster on each diagonal for 2 damage.",
        "Use: strong when diagonal lanes line up and you want one defense to pressure several approach lines at once.",
    ],
    "PowerPlant": [
        "PowerPlant",
        "Type: defense",
        "Abbreviation: pwr",
        "Cost: 2 energy",
        "HP: 1",
        "Recharge: 2 turns",
        "Role: economy defense.",
        "Behavior: starts with 1 turn until its first energy pulse, then generates 1 energy every 4 turns.",
        "Use: invest early so later turns can support more expensive defenses and attackers.",
    ],
    "Backstabber": [
        "Backstabber",
        "Type: defense",
        "Abbreviation: bst",
        "Cost: 2 energy",
        "HP: 1",
        "Recharge: 6 turns",
        "Role: reverse ambush defense.",
        "Behavior: deals 8 damage to the monster in the tile immediately to its left.",
        "Placement rule: to target a monster at row X, col Y, place Backstabber at row X, col Y + 1.",
        "Use: punishes monsters that slip past it or get dropped behind your main line.",
    ],
    "IceTurret": [
        "IceTurret",
        "Type: defense",
        "Abbreviation: ice",
        "Cost: 7 energy",
        "HP: 1",
        "Recharge: 2 turns",
        "Role: control defense.",
        "Behavior: fires at the nearest monster ahead for 1 damage and applies slow.",
        "Slow: slowed monsters only act every other turn.",
        "Use: slows dangerous lanes and buys time for your other defenses.",
    ],
    "Cannon": [
        "Cannon",
        "Type: defense",
        "Abbreviation: can",
        "Cost: 12 energy",
        "HP: 1",
        "Recharge: 2 turns",
        "Role: heavy splash damage.",
        "Behavior: on firing turns, it targets the first monster ahead in its lane, deals 4 damage to that monster, then deals 1 splash damage in a 3x3 box around the target tile.",
        "Cadence: it fires on the first turn after being deployed, then only every other turn.",
        "Use: expensive but excellent when lanes stack multiple monsters close together.",
    ],
    "Vortex": [
        "Vortex",
        "Type: defense",
        "Abbreviation: vor",
        "Cost: 9 energy",
        "HP: 1",
        "Recharge: 6 turns",
        "Role: exact-range burst.",
        "Behavior: each turn, it always targets the tile exactly 3 spaces ahead in its lane. If a monster is standing on that tile, it deals 6 damage; closer or farther monsters are ignored.",
        "Note: if the entry tile is occupied and another monster is queued behind it, Vortex can kill the front monster and the queued one can appear immediately in the same tile. That can make it look like nothing happened, but the shot still resolved correctly.",
        "Use: rewards precise placement and lane timing when you want huge damage at a fixed intercept point.",
    ],
    "LineBomb": [
        "LineBomb",
        "Type: defense",
        "Abbreviation: lin",
        "Cost: 5 energy",
        "HP: 1",
        "Recharge: 10 turns",
        "Role: lane wipe.",
        "Behavior: on its action, it destroys every monster in its entire row and is consumed.",
        "Use: emergency answer when one lane is overwhelmed.",
    ],
    "DoubleTurret": [
        "DoubleTurret",
        "Type: defense",
        "Abbreviation: dbl",
        "Cost: 8 energy",
        "HP: 1",
        "Recharge: 2 turns",
        "Role: high single-lane damage.",
        "Behavior: attacks before monsters move each turn and fires twice for 2 total damage.",
        "Use: stronger than Turret when you can afford the higher energy cost.",
    ],
    "Crusher": [
        "Crusher",
        "Type: defense",
        "Abbreviation: cru",
        "Cost: 6 energy",
        "HP: 1",
        "Recharge: 2 turns",
        "Role: single-target removal.",
        "Behavior: if the tile directly ahead contains a monster, Crusher destroys it outright.",
        "Recharge lockout: after a successful crush, Crusher does nothing for 8 turns.",
        "Use: excellent for deleting one dangerous monster, but weak if lanes stay busy afterward.",
    ],
    "Barricade": [
        "Barricade",
        "Type: defense",
        "Abbreviation: bar",
        "Cost: 2 energy",
        "HP: 8",
        "Recharge: 6 turns",
        "Role: blocker.",
        "Behavior: does not attack; it only absorbs hits.",
        "Use: stalls a lane so your economy or attackers have time to work.",
    ],
    "ForceWall": [
        "ForceWall",
        "Type: defense",
        "Abbreviation: for",
        "Cost: 5 energy",
        "HP: 16",
        "Recharge: 6 turns",
        "Role: anti-jump blocker.",
        "Behavior: does not attack; it absorbs hits and stops Leapers from jumping over it.",
        "Jump rule: if a Leaper meets a ForceWall directly ahead, it loses its leap and stays in place.",
        "Use: high-cost wall for lanes where jumpers would otherwise break your formation.",
    ],
    "AcidSprayer": [
        "AcidSprayer",
        "Type: defense",
        "Abbreviation: acd",
        "Cost: 5 energy",
        "HP: 1",
        "Recharge: 2 turns",
        "Role: short-range line splash.",
        "Behavior: if any monster is within the four tiles directly ahead, it deals 1 damage to every occupied tile in that four-tile stretch.",
        "Use: rewards tight lanes and clustered monsters, especially when several threats stack together.",
    ],
    "Grenade": [
        "Grenade",
        "Type: defense",
        "Abbreviation: gre",
        "Cost: 6 energy",
        "HP: 1",
        "Recharge: 10 turns",
        "Role: burst area clear.",
        "Behavior: explodes on its action, destroys monsters in a 3x3 area around itself, and is consumed.",
        "Use: emergency answer when multiple monsters stack up at once.",
    ],
    "LandMine": [
        "LandMine",
        "Type: defense",
        "Abbreviation: mne",
        "Cost: 1 energy",
        "HP: 1",
        "Recharge: 6 turns",
        "Role: delayed trap.",
        "Behavior: arms over 3 turns. Once armed, it destroys the monster in the tile directly ahead and is consumed.",
        "Use: cheap answer to one monster if you have time to arm it first.",
    ],
    "FreezeMine": [
        "FreezeMine",
        "Type: defense",
        "Abbreviation: frz",
        "Cost: 0 energy",
        "HP: 1",
        "Recharge: 6 turns",
        "Role: instant control trap.",
        "Behavior: starts armed. If the tile directly ahead contains a monster on defense phase, it freezes that monster for 4 turns and is consumed.",
        "Use: a free timing tool for buying time, especially against one dangerous monster in a key lane.",
    ],
    "Skeleton": [
        "Skeleton",
        "Type: monster",
        "Abbreviation: ske",
        "Wave cost: 1 point",
        "HP: 3",
        "Speed: 1 tile per action",
        "Behavior: if a defense is directly ahead, it hits for 1 damage; otherwise it moves left.",
        "Threat: the default pressure unit that tests whether a lane has enough sustained damage.",
    ],
    "Herald": [
        "Herald",
        "Type: monster",
        "Abbreviation: her",
        "Wave cost: 1 point",
        "HP: 3",
        "Speed: 1 tile per action",
        "Behavior: same as a Skeleton, but used to mark a major wave.",
        "Threat: mechanically ordinary, but its arrival signals a major wave milestone.",
    ],
    "Imp": [
        "Imp",
        "Type: monster",
        "Abbreviation: imp",
        "Wave cost: 2 points",
        "HP: 5",
        "Speed: moves every other turn",
        "Behavior: on move turns it behaves like a normal speed-1 monster. On non-move turns, it deals 1 damage to the frontmost defense in its lane.",
        "Threat: chips away at your most advanced defense even when it is not moving, so it pressures lane shape and stall pieces.",
    ],
    "Goblin": [
        "Goblin",
        "Type: monster",
        "Abbreviation: gob",
        "Wave cost: 2 points",
        "HP: 8",
        "Speed: 1 tile per action",
        "Behavior: same movement and attack pattern as a Skeleton, but much tougher.",
        "Threat: survives light damage for longer and can force you to commit real offense to one lane.",
    ],
    "Orc": [
        "Orc",
        "Type: monster",
        "Abbreviation: orc",
        "Wave cost: 4 points",
        "HP: 20",
        "Speed: 1 tile per action",
        "Behavior: same movement and attack pattern as a Skeleton, but with very high durability.",
        "Threat: a late-game tank that can overwhelm weak lanes by sheer health.",
    ],
    "Leaper": [
        "Leaper",
        "Type: monster",
        "Abbreviation: lea",
        "Wave cost: 2 points",
        "HP: 6",
        "Speed: 2 before jump, 1 after jump",
        "Behavior: before jumping, it advances quickly. If the tile directly ahead has a defense, it targets the tile two spaces left as its landing tile.",
        "Landing rule: if that landing tile is empty, it jumps there. If it has a defense, it deals 1 damage; if that defense dies, the Leaper moves into the now-empty tile, otherwise it stays put. If the landing tile has a monster, the jump does not happen.",
        "After jumping: it loses the leap bonus, drops to speed 1, and behaves like a normal monster.",
        "Threat: punishes relying on a single front-line blocker, because it can skip the first defense and may break through the defense behind it too.",
    ],
    "Necromancer": [
        "Necromancer",
        "Type: monster",
        "Abbreviation: nec",
        "Wave cost: 5 points",
        "HP: 5",
        "Speed: acts every other turn",
        "Behavior: on the second time it would act, and every six action turns after that, it summons a Skeleton into every open neighboring tile above, ahead, below, and behind before moving.",
        "Threat: multiplies pressure across nearby tiles, so ignoring it lets one lane become several.",
    ],
    "Gargoyle": [
        "Gargoyle",
        "Type: monster",
        "Abbreviation: gar",
        "Wave cost: 5 points",
        "HP: 10",
        "Speed: moves every other turn while dormant, then speed 3 once awakened",
        "Behavior: while dormant, if a defense is directly ahead it does nothing and deals no damage. The first time it takes damage, it awakens permanently.",
        "Awakened charge: on each action, it attempts to move up to 3 tiles left while carrying 3 attack points. Any occupant in its path is hit for 1 damage per point until destroyed or until the attack points run out.",
        "Threat: punishes poking it without a real plan, because once awakened it can tear through multiple weak occupants in one action.",
    ],
    "Golem": [
        "Golem",
        "Type: monster",
        "Abbreviation: gol",
        "Wave cost: 9 points",
        "HP: 36",
        "Speed: 1 tile per action",
        "Behavior: when the tile ahead contains a defense, it tries to shove the entire contiguous defense chain one tile left. If the leftmost defense is already at column 1, that defense is pushed off the map.",
        "Blocked shove: if any pushed defense would collide with a monster, the shove fails and the Golem does not move that turn.",
        "Threat: breaks carefully spaced formations and can eject key defenses off the board entirely.",
    ],
    "Berserker": [
        "Berserker",
        "Type: monster",
        "Abbreviation: ber",
        "Wave cost: 2 points",
        "HP: 6",
        "Speed: 1 normally, 2 when enraged",
        "Behavior: bites for 1 damage until it drops to 3 HP. At 3 HP or below, it becomes enraged, moves at speed 2, and deals 2 damage per attack.",
        "Threat: punishes partial damage, because weakening it makes it more explosive instead of safer.",
    ],
    "Juggernaut": [
        "Juggernaut",
        "Type: monster",
        "Abbreviation: jug",
        "Wave cost: 7 points",
        "HP: 20",
        "Speed: 2 on its first successful move, then 1",
        "Behavior: crushes any defenses or monsters in every tile it travels through, then ends on the furthest traversed tile.",
        "Threat: a lane-resetting tank that deletes blockers and friendly monsters alike while rolling forward.",
    ],
}


def display_name_for(class_name: str) -> str:
    return DISPLAY_NAME_BY_CLASS.get(class_name, class_name)


def describe_kind(kind: str) -> str:
    if kind == "defense":
        return DEFENSE_LABEL
    if kind == "monster":
        return MONSTER_LABEL
    return kind


def format_special_state(class_name: str, state: str | None) -> str | None:
    if state is None:
        return None
    replacements = {
        "Digesting": "Recharging",
        "Chilled": "Slowed",
    }
    for old, new in replacements.items():
        state = state.replace(old, new)
    return state


@dataclass
class Theme:
    enabled: bool

    def apply(self, text: str, *codes: str) -> str:
        if not self.enabled or not codes:
            return text
        return f"\033[{';'.join(codes)}m{text}\033[0m"


class CliGame:
    def __init__(self, seed: int, no_color: bool, level_id: int = 1, trajectory_logger: TrajectoryLogger | None = None):
        self.seed = seed
        self.level_id = level_id
        self.trajectory_logger = trajectory_logger
        self.theme = Theme(sys.stdout.isatty() and not no_color)
        self.prompt = CLI_PROMPT if sys.stdin.isatty() and sys.stdout.isatty() else ""
        self.level = self.build_level()
        if self.trajectory_logger is not None:
            self.trajectory_logger.log_board_snapshot(
                self.level,
                trigger="initial",
                command=None,
                result="Initial board state.",
            )

    def build_level(self):
        return create_level(level_id=self.level_id, rng_seed=self.seed)

    def restart_level(self):
        self.level = self.build_level()

    def switch_level(self, level_id: int):
        self.level_id = level_id
        self.restart_level()

    def run(self):
        self.print_board_view()
        while True:
            try:
                raw = input(self.prompt)
            except EOFError:
                if self.prompt:
                    print()
                break

            command_line = raw.strip()
            if not command_line:
                continue

            should_exit = self.handle_command(command_line)
            if should_exit:
                break
        if self.trajectory_logger is not None:
            self.trajectory_logger.close(self.level)

    def capture_output(self, func, *args, **kwargs) -> str:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            func(*args, **kwargs)
        return buffer.getvalue().rstrip()

    def current_view_text(self) -> str:
        return self.capture_output(self.print_board_view)

    def execute_command(self, command_line: str) -> tuple[str, bool]:
        command_line = command_line.strip()
        if not command_line:
            return "", False
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            should_exit = self.handle_command(command_line)
        return buffer.getvalue().rstrip(), should_exit

    def handle_command(self, command_line: str) -> bool:
        parts = command_line.split()
        command = parts[0].lower()
        args = parts[1:]

        if self.level.end_state and command not in {"restart", "r", "quit", "q", "exit", "level"}:
            print(self.end_of_game_prompt())
            return False

        if command in {"show", "board"}:
            if not self.require_no_args("show", args):
                return False
            self.print_board_view()
            return False
        if command in {"deploy", "d"}:
            self.handle_deploy(args)
            return False
        if command in {"clear", "c"}:
            self.handle_clear(args)
            return False
        if command in {"inspect", "i"}:
            self.handle_inspect(args)
            return False
        if command in {"guide", "g"}:
            self.handle_guide(args)
            return False
        if command in {"end", "next", "e"}:
            self.handle_end(args)
            return False
        if command == "status":
            self.handle_status(args)
            return False
        if command in {"help", "?"}:
            self.handle_help(args)
            return False
        if command == "instructions":
            self.handle_instructions(args)
            return False
        if command == "level":
            self.handle_level(args)
            return False
        if command in {"restart", "r"}:
            self.handle_restart(args)
            return False
        if command in {"quit", "q", "exit"}:
            if not self.require_no_args("quit", args):
                return False
            return True

        print(f"Unknown command: {command}. Type `help` to see available commands.")
        return False

    def handle_deploy(self, args: list[str]):
        if len(args) < 3:
            print(f"Usage: {COMMAND_USAGE['deploy']}")
            print("Example: deploy powerplant 2 4")
            return

        defense_name = " ".join(args[:-2])
        if not defense_name:
            print(f"Usage: {COMMAND_USAGE['deploy']}")
            print("Example: deploy powerplant 2 4")
            return

        defense_cls = self.resolve_defense_class(defense_name)
        if defense_cls is None:
            print(f"Unknown defense: {defense_name}. Example: deploy powerplant 2 4")
            return

        tile = self.parse_coordinates(args[-2], args[-1])
        if tile is None:
            return
        row, col = tile

        success, reason = self.level.deploy_defense(defense_cls, row, col)
        if not success:
            print(DEPLOY_FAILURE_MESSAGES.get(reason, reason))
            return

        result = f"Deployed {self.display_name(defense_cls.__name__)} at row {row + 1}, column {col + 1}."
        print(result)
        self.print_board_view()
        self.log_trajectory(
            trigger="deploy",
            command=f"deploy {ROSTER_ALIASES.get(defense_cls.__name__, defense_cls.__name__.lower())} {row + 1} {col + 1}",
            result=result,
        )

    def handle_clear(self, args: list[str]):
        if len(args) != 2:
            print(f"Usage: {COMMAND_USAGE['clear']}")
            print("Example: clear 2 4")
            return

        tile = self.parse_coordinates(args[0], args[1])
        if tile is None:
            return
        row, col = tile

        success, reason = self.level.clear_defense(row, col)
        if not success:
            print(CLEAR_FAILURE_MESSAGES.get(reason, reason))
            return

        result = f"Cleared row {row + 1}, column {col + 1}."
        print(result)
        self.print_board_view()
        self.log_trajectory(
            trigger="clear",
            command=f"clear {row + 1} {col + 1}",
            result=result,
        )

    def handle_inspect(self, args: list[str]):
        if len(args) != 2:
            print(f"Usage: {COMMAND_USAGE['inspect']}")
            print("Example: inspect 1 9")
            return

        tile = self.parse_coordinates(args[0], args[1])
        if tile is None:
            return
        row, col = tile

        description = self.level.describe_tile(row, col)
        if description["empty"]:
            if description["entry_column"]:
                print(f"Tile {row + 1}, {col + 1} is empty. This is the monster entry column.")
            else:
                print(f"Tile {row + 1}, {col + 1} is empty.")
            return

        occupant = description["occupant"]
        lines = [
            f"Tile {row + 1}, {col + 1}: {self.display_name(occupant['name'])}",
            f"HP: {occupant['hp']}",
        ]
        special_state = format_special_state(occupant["name"], occupant["special_state"])
        if special_state:
            lines.append(f"State: {special_state}")
        if occupant["kind"] == "monster" and occupant.get("wave_number") is not None:
            lines.append(f"Wave: {occupant['wave_number']}")
        print("\n".join(lines))

    def handle_guide(self, args: list[str]):
        if len(args) != 1:
            print(f"Usage: {COMMAND_USAGE['guide']}")
            print("Examples: guide tur, guide lea, guide powerplant")
            return

        class_name = self.resolve_guide_target(args[0])
        if class_name is None:
            print(f"Unknown field guide entry: {args[0]}. Example: guide tur")
            return

        print("\n".join(GUIDE_ENTRIES.get(class_name, [self.display_name(class_name)])))

    def handle_end(self, args: list[str]):
        if not self.require_no_args("next", args):
            return

        self.level.run_turn()
        self.print_board_view()
        result = f"Turn {self.level.turn_count} complete."
        if self.level.end_state:
            print(self.end_banner())
            print(self.end_of_game_prompt())
            result = "You win." if self.level.end_state == "Win" else "You lose."
        self.log_trajectory(trigger="next", command="next", result=result)

    def handle_status(self, args: list[str]):
        if not self.require_no_args("status", args):
            return

        snapshot = self.level.snapshot()
        print(f"Level: {snapshot['level_name']}")
        print(f"Turn: {snapshot['turn_count']}")
        print(f"Energy: {snapshot['energy']}")

        roster = []
        for status in self.level.available_defense_statuses():
            alias = ROSTER_ALIASES.get(status["name"], status["name"].lower())
            if status["cooldown_remaining"] > 0:
                readiness = f"cd:{status['cooldown_remaining']}"
            elif status["ready"]:
                readiness = "ready"
            else:
                readiness = "low"
            roster.append(f"{alias} {status['cost']} {readiness}")
        print("Loadout: " + " | ".join(roster))

        occupants = self.describe_all_occupants()
        if not occupants:
            print("Entities: none")
            return

        print("Entities:")
        for line in occupants:
            print(f"- {line}")

    def handle_help(self, args: list[str]):
        if not self.require_no_args("help", args):
            return

        defense_tokens = " ".join(
            f"{TOKEN_BY_NAME.get(defense_cls.__name__, defense_cls.__name__[:3])}:{defense_cls().hp}"
            for defense_cls in self.level.definition.defense_roster
        )
        monster_tokens = " ".join(
            f"{TOKEN_BY_NAME.get(monster_cls.__name__, monster_cls.__name__[:3])}:{monster_cls().hp}"
            for monster_cls in self.instruction_monster_classes()
        )
        help_lines = [
            "Commands:",
            "  show | board",
            "  deploy <name> <row> <col>  Example: deploy powerplant 2 4",
            "  clear <row> <col>          Example: clear 2 4",
            f"  inspect <row> <col>        Example: inspect 1 {self.level.board.entry_col + 1}",
            "  guide <abbr>               Detailed field guide entry",
            "  next                       Advance exactly one turn",
            "  status",
            "  level <number>             Load a different level",
            "  instructions               Full gameplay guide",
            "  restart",
            "  quit",
            "Defense names ignore case, spaces, hyphens, and underscores.",
            f"Available levels: {', '.join(str(level_id) for level_id in available_level_ids())}.",
            f"Columns 1-{self.level.definition.deployable_cols} are deployable. Column {self.level.board.entry_col + 1} is monster-entry only.",
            "",
            "Board legend:",
            "  Tokens are <abbr>:<hp>.",
            f"  Defenses in this level: {defense_tokens}",
            f"  Monsters in this level: {monster_tokens}",
            "  . means an empty tile.",
            f"  Column {self.level.board.entry_col + 1} is the entry column, so you can inspect it but not deploy there.",
            "",
            "Loadout legend:",
            "  Each entry is <alias> <energy-cost> <state>.",
            "  ready means you can deploy it now.",
            "  cd:N means the card is recharging for N more turns.",
            f"  low means you do not have enough {RESOURCE_LABEL} for it right now.",
            "",
            "Examples:",
            "  deploy pwr 2 4",
            "  deploy barricade 3 5",
            "  guide lea",
            f"  inspect 1 {self.level.board.entry_col + 1}",
            "  level 2",
            "  clear 2 4",
            "  next",
        ]
        print("\n".join(help_lines))

    def handle_instructions(self, args: list[str]):
        if not self.require_no_args("instructions", args):
            return

        lines = [
            "Instructions:",
            "  This is a turn-based tower defense benchmark.",
            "  Goal: survive the monster waves.",
            "  Loss: if a monster reaches the left edge of the grid, you lose.",
            "  Turn flow: deploy, clear, or inspect as needed, then type `next` to resolve one turn.",
            f"  Energy: defenses cost {RESOURCE_LABEL}. You start with 2 {RESOURCE_LABEL}, gain 1 ambient {RESOURCE_LABEL} every 2 turns, and power plants make extra {RESOURCE_LABEL}.",
            "  Monsters: monsters enter from the right side and move left over time.",
            f"  Board shape: columns 1-{self.level.definition.deployable_cols} are deployable; column {self.level.board.entry_col + 1} is monster-entry only.",
            "  Recommendation: before playing a new level, use `guide` on every defense and monster in that level.",
            "",
            "Defenses in this level:",
            *[f"  {DEFENSE_DESCRIPTIONS.get(defense_cls.__name__, defense_cls.__name__)}" for defense_cls in self.level.definition.defense_roster],
            "",
            "Monsters in this level:",
            *[f"  {MONSTER_DESCRIPTIONS.get(monster_cls.__name__, monster_cls.__name__)}" for monster_cls in self.instruction_monster_classes()],
            "",
            "Mechanics:",
            "  Most monsters hit the defense directly in front of them for 1 damage.",
            "  Some special monsters break that rule; use `guide` to check exact behavior.",
            "  If no defense is in front of a monster, it moves forward.",
            f"  Defenses attack or generate {RESOURCE_LABEL} before monsters move each turn.",
            "  You cannot place a defense on an occupied tile.",
            "  A tile cannot have more than one occupant: defense or monster.",
            f"  Type `level {self.level_id}` to restart the current level or `level X` to switch levels.",
            "",
            "Type `help` for the quick reference and board legend.",
        ]
        print("\n".join(lines))

    def handle_level(self, args: list[str]):
        if len(args) != 1:
            print(f"Usage: {COMMAND_USAGE['level']}")
            print(f"Available levels: {', '.join(str(level_id) for level_id in available_level_ids())}")
            return
        try:
            level_id = int(args[0])
        except ValueError:
            print("Level must be a number.")
            return
        if level_id not in available_level_ids():
            print(f"Unknown level: {level_id}. Available levels: {', '.join(str(level) for level in available_level_ids())}.")
            return
        self.switch_level(level_id)
        result = f"Loaded {self.level.definition.name}."
        print(result)
        self.print_board_view()
        self.log_trajectory(trigger="level", command=f"level {level_id}", result=result)

    def handle_restart(self, args: list[str]):
        if not self.require_no_args("restart", args):
            return

        self.restart_level()
        result = "Level restarted."
        print(result)
        self.print_board_view()
        self.log_trajectory(trigger="restart", command="restart", result=result)

    def log_trajectory(self, trigger: str, command: str | None, result: str):
        if self.trajectory_logger is None:
            return
        self.trajectory_logger.log_board_snapshot(
            self.level,
            trigger=trigger,
            command=command,
            result=result,
        )

    def require_no_args(self, command: str, args: list[str]) -> bool:
        if args:
            print(f"Usage: {COMMAND_USAGE[command]}")
            return False
        return True

    def parse_coordinates(self, row_text: str, col_text: str):
        try:
            row = int(row_text)
            col = int(col_text)
        except ValueError:
            print("Row and column must be numbers. Example: deploy powerplant 2 4")
            return None

        if not (1 <= row <= self.level.board.rows and 1 <= col <= self.level.board.cols):
            print(
                f"Coordinates out of range. Rows are 1-{self.level.board.rows} and columns are 1-{self.level.board.cols}."
            )
            return None
        return row - 1, col - 1

    def resolve_defense_class(self, raw_name: str):
        normalized = self.normalize_name(raw_name)
        for alias, canonical in DEFENSE_ALIASES.items():
            if self.normalize_name(alias) == normalized:
                for defense_cls in self.level.definition.defense_roster:
                    if defense_cls.__name__ == canonical:
                        return defense_cls
                return None
        for defense_cls in self.level.definition.defense_roster:
            if self.normalize_name(defense_cls.__name__) == normalized:
                return defense_cls
            if self.normalize_name(display_name_for(defense_cls.__name__)) == normalized:
                return defense_cls
        return None

    def resolve_guide_target(self, raw_name: str):
        normalized = self.normalize_name(raw_name)

        for alias, canonical in GUIDE_ALIASES.items():
            if self.normalize_name(alias) == normalized:
                return canonical

        for canonical in GUIDE_ENTRIES:
            if self.normalize_name(canonical) == normalized:
                return canonical
            if self.normalize_name(display_name_for(canonical)) == normalized:
                return canonical

        return None

    def normalize_name(self, text: str) -> str:
        return "".join(ch for ch in text.lower() if ch.isalnum())

    def display_name(self, class_name: str) -> str:
        return display_name_for(class_name)

    def print_board_view(self):
        snapshot = self.level.snapshot()
        print(self.header_line(snapshot))
        print(self.render_board())
        print(self.render_roster_strip())
        print(f"Entry column: {self.level.board.entry_col + 1} (monster-only)")
        print("deploy <name> <row> <col> | clear <row> <col> | inspect <row> <col> | next | level <n> | help | instructions | quit")

    def header_line(self, snapshot: dict) -> str:
        pieces = [
            self.theme.apply(snapshot["level_name"], "1", "36"),
            f"Turn {snapshot['turn_count']}",
            self.theme.apply(f"Energy {snapshot['energy']}", "1", "33"),
            f"Waves {snapshot['spawned_waves']}/{snapshot['total_waves']}",
        ]
        if snapshot["end_state"]:
            pieces.append(self.theme.apply(snapshot["end_state"], "1", "31"))
        return " | ".join(pieces)

    def render_board(self) -> str:
        rows = self.level.board.rows
        cols = self.level.board.cols
        header_cells = " ".join(
            self.theme.apply(f"{str(col + 1):^{CELL_WIDTH}}", "1", "35") if self.level.board.is_entry_column(col)
            else f"{str(col + 1):^{CELL_WIDTH}}"
            for col in range(cols)
        )
        border = "   +" + "+".join("-" * CELL_WIDTH for _ in range(cols)) + "+"
        lines = [f"    {header_cells}", border]
        for row in range(rows):
            cells = []
            for col in range(cols):
                tile = self.level.describe_tile(row, col)
                if tile["empty"]:
                    raw = f"{'.':^{CELL_WIDTH}}"
                    if tile["entry_column"]:
                        cells.append(self.theme.apply(raw, "2", "35"))
                    else:
                        cells.append(self.theme.apply(raw, "2"))
                    continue

                occupant = tile["occupant"]
                token = f"{TOKEN_BY_NAME.get(occupant['name'], occupant['name'][:3])}:{occupant['hp']}"
                raw = f"{token:^{CELL_WIDTH}}"
                if occupant["kind"] == "defense":
                    if occupant["name"] == "PowerPlant":
                        cells.append(self.theme.apply(raw, "1", "33"))
                    elif occupant["name"] == "Barricade":
                        cells.append(self.theme.apply(raw, "1", "37"))
                    else:
                        cells.append(self.theme.apply(raw, "1", "32"))
                else:
                    cells.append(self.theme.apply(raw, "1", "31"))
            lines.append(f"{row + 1:>2} |" + "|".join(cells) + "|")
            lines.append(border)
        return "\n".join(lines)

    def render_roster_strip(self) -> str:
        pieces = []
        for status in self.level.available_defense_statuses():
            alias = ROSTER_ALIASES.get(status["name"], status["name"].lower())
            if status["cooldown_remaining"] > 0:
                state = f"cd:{status['cooldown_remaining']}"
                segment = self.theme.apply(f"{alias} {status['cost']} {state}", "36")
            elif status["ready"]:
                segment = self.theme.apply(f"{alias} {status['cost']} ready", "32")
            else:
                segment = self.theme.apply(f"{alias} {status['cost']} low", "33")
            pieces.append(segment)
        return "Loadout: " + " | ".join(pieces)

    def describe_all_occupants(self) -> list[str]:
        occupants = []
        for row in range(self.level.board.rows):
            for col in range(self.level.board.cols):
                tile = self.level.describe_tile(row, col)
                if tile["empty"]:
                    continue
                occupant = tile["occupant"]
                parts = [
                    f"{self.display_name(occupant['name'])} at row {row + 1}, column {col + 1}",
                    f"HP {occupant['hp']}",
                ]
                special_state = format_special_state(occupant["name"], occupant["special_state"])
                if special_state:
                    parts.append(special_state)
                if occupant["kind"] == "monster" and occupant.get("wave_number") is not None:
                    parts.append(f"wave {occupant['wave_number']}")
                occupants.append(" | ".join(parts))
        return occupants

    def instruction_monster_classes(self):
        seen = []
        for monster_cls in self.level.definition.monster_roster:
            if monster_cls not in seen:
                seen.append(monster_cls)
        for wave_config in self.level.definition.wave_configs.values():
            for spawn in wave_config.scripted_spawns:
                if spawn.monster_cls not in seen:
                    seen.append(spawn.monster_cls)
        return seen

    def end_banner(self) -> str:
        if self.level.end_state == "Win":
            return self.theme.apply("You win.", "1", "32")
        return self.theme.apply("You lose.", "1", "31")

    def end_of_game_prompt(self) -> str:
        return f"The game is over. Type `level {self.level_id}` to replay or `quit` to leave."


def main():
    parser = argparse.ArgumentParser(description="Play the turn-based tower defense benchmark in a guided CLI.")
    parser.add_argument("--seed", type=int, default=7, help="Random seed for the demo level.")
    parser.add_argument("--level", type=int, default=1, help="Level number to load.")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors.")
    parser.add_argument("--log-dir", type=Path, default=None, help="Directory for optional JSONL trajectory logs of your manual run.")
    args = parser.parse_args()

    trajectory_logger = None
    if args.log_dir is not None:
        trajectory_logger = TrajectoryLogger(
            log_dir=args.log_dir,
            interface="cli",
            seed=args.seed,
            level_id=args.level,
        )
        print(f"[trajectory log] {trajectory_logger.path}")

    CliGame(
        seed=args.seed,
        no_color=args.no_color,
        level_id=args.level,
        trajectory_logger=trajectory_logger,
    ).run()


if __name__ == "__main__":
    main()
