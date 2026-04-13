from abc import ABC, abstractmethod
from collections import deque
import random

INSTANT_DAMAGE = 27
class Tile:
    def __init__(self, row, col):
        self.occupant = None
        self.row = row
        self.col = col

class Board:
    def __init__(self, rows, cols):
        self.rows = rows
        self.cols = cols
        self.tiles = [[Tile(row, col) for col in range(cols)] for row in range(rows)]
        self.entry_queues = [deque() for _ in range(rows)]
        self.end_state = None
        self.turn_count = 0
        self.level = None

    @property
    def entry_col(self):
        return self.cols - 1

    @property
    def deployable_cols(self):
        if self.level is not None:
            return self.level.definition.deployable_cols
        return self.cols

    def is_deployable_col(self, col):
        return 0 <= col < self.deployable_cols

    def is_entry_column(self, col):
        return col == self.entry_col

    def trigger_end_state(self, state):
        self.end_state = state
    def add_occupant(self, occupant, row, col):
        if isinstance(occupant, Defense) and not self.is_deployable_col(col):
            raise ValueError("Defenses cannot occupy the monster entry column")
        if self.tiles[row][col].occupant is None:
            self.tiles[row][col].occupant = occupant
            occupant.board = self
            occupant.level = self.level
            occupant.tile = self.tiles[row][col]
        else:
            raise ValueError("Tile is already occupied")
    def remove_entity(self, entity):
        row = entity.tile.row
        col = entity.tile.col
        self.tiles[row][col].occupant = None
        entity.board = None
        entity.level = None
        entity.tile = None
        if col == self.entry_col:
            self.flush_entry_queue(row)
    def move_entity(self, entity, new_row, new_col):
        if self.tiles[new_row][new_col].occupant is None:
            old_row = entity.tile.row
            old_col = entity.tile.col
            self.tiles[old_row][old_col].occupant = None
            self.tiles[new_row][new_col].occupant = entity
            entity.tile = self.tiles[new_row][new_col]
            if old_col == self.entry_col:
                self.flush_entry_queue(old_row)
        else:
            raise ValueError("Tile is already occupied")
    def row_has_space(self, row):
        return any(tile.occupant is None for tile in self.tiles[row])

    def queue_monster(self, monster, row, queued_turn):
        self.entry_queues[row].append({"monster": monster, "queued_turn": queued_turn})

    def flush_entry_queue(self, row):
        entry_col = self.entry_col
        if self.tiles[row][entry_col].occupant is not None:
            return None
        if not self.entry_queues[row]:
            return None
        pending = self.entry_queues[row].popleft()
        monster = pending["monster"]
        monster.spawn_turn = self.turn_count + 1
        self.add_occupant(monster, row, entry_col)
        return monster

    def spawn_monster(self, monster_cls, row, wave_number=None):
        entry_col = self.entry_col
        monster = monster_cls()
        monster.wave_number = wave_number
        if self.tiles[row][entry_col].occupant is not None:
            self.queue_monster(monster, row, queued_turn=self.turn_count + 1)
            return None
        monster.spawn_turn = self.turn_count + 1
        self.add_occupant(monster, row, entry_col)
        return monster

    def run_entry_queue_actions(self, resolved_turn):
        entry_col = self.entry_col
        for row, queue in enumerate(self.entry_queues):
            if not queue:
                continue
            if self.tiles[row][entry_col].occupant is None:
                self.flush_entry_queue(row)
                continue

            pending = queue[0]
            monster = pending["monster"]
            if pending["queued_turn"] == resolved_turn:
                continue
            if monster.should_skip_action():
                continue
            monster.act_from_spawn_queue(self, row)
            monster.finish_action_phase()
    def scan_ahead(self, row, col, direction, max_distance=None, criteria=lambda occupant: True):
        if max_distance is None:
            max_distance = self.cols
        for i in range(1, max_distance + 1):
            new_col = col + direction * i
            if 0 <= new_col < self.cols:
                occupant = self.tiles[row][new_col].occupant
                if occupant is not None and criteria(occupant):
                    return occupant
        return None
    def scan_in_direction(self, row, col, row_step, col_step, max_distance=None, criteria=lambda occupant: True):
        if max_distance is None:
            max_distance = max(self.rows, self.cols)
        for i in range(1, max_distance + 1):
            new_row = row + row_step * i
            new_col = col + col_step * i
            if not (0 <= new_row < self.rows and 0 <= new_col < self.cols):
                break
            occupant = self.tiles[new_row][new_col].occupant
            if occupant is not None and criteria(occupant):
                return occupant
        return None
    def scan_around(self, row, col, radius, criteria=lambda occupant: True):
        found = []
        for r in range(max(0, row - radius), min(self.rows, row + radius + 1)):
            for c in range(max(0, col - radius), min(self.cols, col + radius + 1)):
                occupant = self.tiles[r][c].occupant
                if occupant is not None and criteria(occupant):
                    found.append(occupant)
        return found
    def scan_entities(self, criteria):
        found = []
        for row in self.tiles:
            for tile in row:
                if tile.occupant and criteria(tile.occupant):
                    found.append(tile.occupant)
        return found
    def run_turn(self):
        if self.end_state:
            return
        resolved_turn = self.turn_count + 1
        defenses = self.scan_entities(lambda occupant: isinstance(occupant, Defense))
        defenses.sort(key=lambda defense: defense.tile.col * 100 + defense.tile.row)
        for defense in defenses:
            if defense.tile.occupant is defense:
                defense.act()
        monsters = self.scan_entities(lambda occupant: isinstance(occupant, Monster))
        monsters.sort(key=lambda z: z.tile.col * 100 + z.tile.row) # Monsters act from left to right, top to bottom
        for monster in monsters:
            if monster.tile.occupant is monster:  # Check if the monster is still alive before acting
                if monster.spawn_turn == resolved_turn:
                    continue
                if monster.should_skip_action():
                    continue
                monster.act()
                monster.finish_action_phase()
        self.run_entry_queue_actions(resolved_turn)
        self.turn_count += 1
    
    def to_ascii(self):
        ascii_board = ""
        for row in self.tiles:
            for tile in row:
                if tile.occupant is None:
                    ascii_board += ". "
                else:
                    name = tile.occupant.name
                    ascii_board += name[0] + " "
            ascii_board += "\n"
        return ascii_board
    def state(self):
        defense_states = []
        monster_states = []
        for row in self.tiles:
            for tile in row:
                if tile.occupant is not None:
                    occupant = tile.occupant
                    state_str = f"{occupant.name} at ({tile.row}, {tile.col}) with {occupant.hp} HP"
                    if occupant.special_state() is not None:
                        state_str += f" - {occupant.special_state()}"
                    if isinstance(occupant, Defense):
                        defense_states.append(state_str)
                    else:
                        monster_states.append(state_str)

        return "\n".join(defense_states + monster_states)
    
class Entity(ABC):
    def __init__(self, name, hp):
        self.name = name
        self.hp = hp
        self.board = None
        self.level = None
        self.tile = None
    @abstractmethod
    def act(self):
        pass
    def take_damage(self, amount):
        self.hp -= amount
        if self.hp <= 0:
            self.die()
    def die(self):
        self.board.remove_entity(self)
    def special_state(self):
        return None

class Defense(Entity):
    cost = 0
    cooldown = 0
    special_init_cooldown = None

    def __init__(self, name, hp):
        super().__init__(name, hp)


class Monster(Entity):
    wave_cost = 0
    first_allowed_wave = 1
    pick_weight = 0

    def __init__(self, name, hp):
        super().__init__(name, hp)
        self.wave_number = None
        self.skip_next_action = False
        self.spawn_turn = None
        self.counts_toward_wave_health = True
        self.chilled = False
        self.chill_phase = 0
        self.frozen_turns = 0

    def apply_chilled(self):
        if not self.chilled:
            self.chilled = True
            self.chill_phase = 1

    def apply_frozen(self, turns=4):
        self.frozen_turns = max(self.frozen_turns, turns)

    def should_skip_action(self):
        if self.frozen_turns > 0:
            self.frozen_turns -= 1
            return True
        if not self.chilled:
            return False
        if self.chill_phase % 2 == 1:
            self.chill_phase += 1
            return True
        return False

    def finish_action_phase(self):
        if self.chilled:
            self.chill_phase += 1

    def queue_attack_damage(self):
        return getattr(self, "attack_damage", 1)

    def act_from_spawn_queue(self, board, row):
        entry_col = board.cols - 1
        occupant = board.tiles[row][entry_col].occupant
        if occupant is None:
            board.flush_entry_queue(row)
            return
        if not isinstance(occupant, Defense):
            return
        occupant.take_damage(self.queue_attack_damage())
        if board.tiles[row][entry_col].occupant is None:
            board.flush_entry_queue(row)

    def status_labels(self):
        labels = []
        if self.frozen_turns > 0:
            labels.append(f"Frozen: {self.frozen_turns}")
        elif self.chilled:
            labels.append("Chilled")
        return labels

    def special_state(self):
        labels = self.status_labels()
        return ", ".join(labels) if labels else None

class Turret(Defense):
    cost = 4
    cooldown = 2

    def __init__(self):
        super().__init__("Turret", 1)
    def act(self):
        target = self.board.scan_ahead(self.tile.row, self.tile.col, 1, criteria=lambda occupant: isinstance(occupant, Monster))
        if target:
            target.take_damage(1)


class QuadTurret(Defense):
    cost = 6
    cooldown = Turret.cooldown

    def __init__(self):
        super().__init__("QuadTurret", 1)

    def act(self):
        for row_step, col_step in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
            target = self.board.scan_in_direction(
                self.tile.row,
                self.tile.col,
                row_step,
                col_step,
                criteria=lambda occupant: isinstance(occupant, Monster),
            )
            if target:
                target.take_damage(2)


class IceTurret(Defense):
    cost = 7
    cooldown = 2

    def __init__(self):
        super().__init__("IceTurret", 1)

    def act(self):
        target = self.board.scan_ahead(self.tile.row, self.tile.col, 1, criteria=lambda occupant: isinstance(occupant, Monster))
        if target:
            target.take_damage(1)
            if target.board is not None:
                target.apply_chilled()


class DoubleTurret(Defense):
    cost = 8
    cooldown = 2

    def __init__(self):
        super().__init__("DoubleTurret", 1)

    def act(self):
        target = self.board.scan_ahead(self.tile.row, self.tile.col, 1, criteria=lambda occupant: isinstance(occupant, Monster))
        if target:
            target.take_damage(2)


class Backstabber(Defense):
    cost = 2
    cooldown = 6

    def __init__(self):
        super().__init__("Backstabber", 1)

    def act(self):
        target_col = self.tile.col - 1
        if target_col < 0:
            return
        target = self.board.tiles[self.tile.row][target_col].occupant
        if isinstance(target, Monster):
            target.take_damage(8)

class PowerPlant(Defense):
    cost = 2
    cooldown = 2
    special_init_cooldown = 0
    initial_turns_to_generate = 1
    turns_between_energy = 4

    def __init__(self):
        super().__init__("PowerPlant", 1)
        self.turns_to_generate = self.initial_turns_to_generate
    def act(self):
        self.turns_to_generate -= 1
        if self.turns_to_generate <= 0:
            self.level.energy += 1
            self.turns_to_generate = self.turns_between_energy
    def special_state(self):
        return f"Turns to generate energy: {self.turns_to_generate}"

class Barricade(Defense):
    cost = 2
    cooldown = 6

    def __init__(self):
        super().__init__("Barricade", 8)
    def act(self):
        pass  # Barricades only absorb damage.


class ForceWall(Defense):
    cost = 5
    cooldown = Barricade.cooldown

    def __init__(self):
        super().__init__("ForceWall", 16)

    def act(self):
        pass


class Cannon(Defense):
    cost = 12
    cooldown = Turret.cooldown

    def __init__(self):
        super().__init__("Cannon", 1)
        self.ready_to_fire = True

    def act(self):
        if not self.ready_to_fire:
            self.ready_to_fire = True
            return

        self.ready_to_fire = False
        target = self.board.scan_ahead(
            self.tile.row,
            self.tile.col,
            1,
            criteria=lambda occupant: isinstance(occupant, Monster),
        )
        if not target:
            return

        target_row = target.tile.row
        target_col = target.tile.col
        target.take_damage(4)
        splash_targets = self.board.scan_around(
            target_row,
            target_col,
            radius=1,
            criteria=lambda occupant: isinstance(occupant, Monster),
        )
        for splash_target in splash_targets:
            splash_target.take_damage(1)

    def special_state(self):
        return "Ready" if self.ready_to_fire else "Reloading"


class Vortex(Defense):
    cost = 9
    cooldown = Barricade.cooldown

    def __init__(self):
        super().__init__("Vortex", 1)

    def act(self):
        target_col = self.tile.col + 3
        if target_col >= self.board.cols:
            return
        target = self.board.tiles[self.tile.row][target_col].occupant
        if isinstance(target, Monster):
            target.take_damage(6)


class LineBomb(Defense):
    cost = 5
    cooldown = 10

    def __init__(self):
        super().__init__("LineBomb", 1)

    def act(self):
        for col in range(self.board.cols):
            occupant = self.board.tiles[self.tile.row][col].occupant
            if isinstance(occupant, Monster):
                occupant.take_damage(INSTANT_DAMAGE)
        self.die()


class AcidSprayer(Defense):
    cost = 5
    cooldown = Turret.cooldown

    def __init__(self):
        super().__init__("AcidSprayer", 1)

    def act(self):
        targets = []
        for distance in range(1, 5):
            target_col = self.tile.col + distance
            if target_col >= self.board.cols:
                break
            occupant = self.board.tiles[self.tile.row][target_col].occupant
            if isinstance(occupant, Monster):
                targets.append(occupant)

        if not targets:
            return

        for target in targets:
            target.take_damage(1)


class Crusher(Defense):
    cost = 6
    cooldown = 2

    def __init__(self):
        super().__init__("Crusher", 1)
        self.turns_to_digest = 0

    def act(self):
        if self.turns_to_digest > 0:
            self.turns_to_digest -= 1
            return
        target = self.board.scan_ahead(
            self.tile.row,
            self.tile.col,
            1,
            max_distance=1,
            criteria=lambda occupant: isinstance(occupant, Monster),
        )
        if target:
            target.die()
            self.turns_to_digest = 8

    def special_state(self):
        if self.turns_to_digest > 0:
            return f"Digesting: {self.turns_to_digest}"
        return None

class Grenade(Defense):
    cost = 6
    cooldown = 10

    def __init__(self):
        super().__init__("Grenade", 1)
    def act(self):
        targets = self.board.scan_around(self.tile.row, self.tile.col, radius=1, criteria=lambda occupant: isinstance(occupant, Monster))
        for target in targets:
            target.take_damage(INSTANT_DAMAGE) # Damage instant kills
        self.die()  # Single-use explosive.
    
    
class LandMine(Defense):
    cost = 1
    cooldown = 6

    def __init__(self):
        super().__init__("LandMine", 1)
        self.turns_to_arm = 3
    def act(self):
        if self.turns_to_arm > 0:
            self.turns_to_arm -= 1
        else:
            target = self.board.scan_ahead(self.tile.row, self.tile.col, 1, max_distance=1, criteria=lambda occupant: isinstance(occupant, Monster))  # Adjacent trigger only.
            if target:
                target.take_damage(INSTANT_DAMAGE)
                self.die()  # Single-use trap.
    def special_state(self):
        if self.turns_to_arm > 0:
            return f"Turns to arm: {self.turns_to_arm}"
        else:
            return "Armed"


class FreezeMine(Defense):
    cost = 0
    cooldown = Barricade.cooldown

    def __init__(self):
        super().__init__("FreezeMine", 1)
        self.turns_to_arm = 0

    def act(self):
        target = self.board.scan_ahead(
            self.tile.row,
            self.tile.col,
            1,
            max_distance=1,
            criteria=lambda occupant: isinstance(occupant, Monster),
        )
        if target:
            target.apply_frozen(4)
            self.die()

    def special_state(self):
        return "Armed"
        
class DeployClient:
    def __init__(self, level):
        self.level = level
        self.cooldowns = {}
    def add_defense_class(self, defense_cls):
        initial_cooldown = defense_cls.special_init_cooldown
        if initial_cooldown is None:
            initial_cooldown = defense_cls.cooldown
        self.cooldowns[defense_cls] = initial_cooldown
    def can_deploy(self, defense_cls):
        return self.level.energy >= defense_cls.cost and self.cooldowns.get(defense_cls, 0) == 0
    def deployment_failure_reason(self, defense_cls, row, col):
        if not self.level.board.is_deployable_col(col):
            return "entry column not deployable"
        if self.level.energy < defense_cls.cost:
            return "not enough energy"
        if self.cooldowns.get(defense_cls, 0) != 0:
            return "cooldown active"
        if self.level.board.tiles[row][col].occupant is not None:
            return "tile occupied"
        return None
    def deploy_defense(self, defense_cls, row, col):
        reason = self.deployment_failure_reason(defense_cls, row, col)
        if reason is None:
            self.level.energy -= defense_cls.cost
            self.level.board.add_occupant(defense_cls(), row, col)
            self.cooldowns[defense_cls] = defense_cls.cooldown
            return True, None
        else:
            return False, reason
    def tick(self):
        for defense_cls in self.cooldowns:
            if self.cooldowns[defense_cls] > 0:
                self.cooldowns[defense_cls] -= 1
    def state(self):
        cooldown_states = [f"{defense_cls.__name__} cooldown: {self.cooldowns[defense_cls]}" for defense_cls in self.cooldowns]
        return "\n".join(cooldown_states)


class ClearClient:
    def __init__(self, level):
        self.level = level

    def clear_failure_reason(self, row, col):
        occupant = self.level.board.tiles[row][col].occupant
        if occupant is None:
            return "tile empty"
        if not isinstance(occupant, Defense):
            return "cannot clear monsters"
        return None

    def clear_defense(self, row, col):
        reason = self.clear_failure_reason(row, col)
        if reason is not None:
            return False, reason
        self.level.board.remove_entity(self.level.board.tiles[row][col].occupant)
        return True, None
    


class Skeleton(Monster):
    wave_cost = 1
    first_allowed_wave = 1
    pick_weight = 4000

    def __init__(self, name="Skeleton", hp=3, speed=1):
        super().__init__(name, hp)
        self.speed = speed
        self.attack_damage = 1

    def move_or_attack(self):
        move_distance = 0
        for step in range(1, self.speed + 1):
            target_col = self.tile.col - step
            if target_col < 0:
                self.board.trigger_end_state("Loss")
                return

            occupant = self.board.tiles[self.tile.row][target_col].occupant
            if occupant is None:
                move_distance = step
                continue

            if move_distance == 0 and isinstance(occupant, Defense):
                occupant.take_damage(self.attack_damage)
                return
            break

        if move_distance > 0:
            self.board.move_entity(self, self.tile.row, self.tile.col - move_distance)

    def act(self):
        self.move_or_attack()

class Herald(Skeleton):
    pick_weight = 0

    def __init__(self):
        super().__init__(name="Herald", hp=3)


class Imp(Skeleton):
    wave_cost = 2
    first_allowed_wave = 1
    pick_weight = 2600

    def __init__(self):
        super().__init__(name="Imp", hp=5, speed=1)
        self.move_phase = False

    def frontmost_defense(self):
        for col in range(self.board.cols - 1, -1, -1):
            occupant = self.board.tiles[self.tile.row][col].occupant
            if isinstance(occupant, Defense):
                return occupant
        return None

    def act(self):
        if self.move_phase:
            self.move_or_attack()
        else:
            target = self.frontmost_defense()
            if target:
                target.take_damage(1)
        self.move_phase = not self.move_phase

    def special_state(self):
        states = self.status_labels()
        states.append("Moves next" if self.move_phase else "Pokes lane")
        return ", ".join(states)

class Goblin(Skeleton):
    wave_cost = 2
    first_allowed_wave = 4
    pick_weight = 4000

    def __init__(self):
        super().__init__(name="Goblin", hp=8)

class Orc(Skeleton):
    wave_cost = 4
    first_allowed_wave = 8
    pick_weight = 3000

    def __init__(self):
        super().__init__(name="Orc", hp=20)


class Leaper(Skeleton):
    wave_cost = 2
    first_allowed_wave = 5
    pick_weight = 2600

    def __init__(self):
        super().__init__(name="Leaper", hp=6, speed=2)
        self.has_vaulted = False

    def act(self):
        if not self.has_vaulted:
            front_col = self.tile.col - 1
            if front_col < 0:
                self.board.trigger_end_state("Loss")
                return
            front_occupant = self.board.tiles[self.tile.row][front_col].occupant
            if isinstance(front_occupant, ForceWall):
                self.has_vaulted = True
                self.speed = 1
                return
            if isinstance(front_occupant, Defense):
                landing_col = self.tile.col - 2
                if landing_col < 0:
                    self.board.trigger_end_state("Loss")
                    return
                landing_occupant = self.board.tiles[self.tile.row][landing_col].occupant
                if isinstance(landing_occupant, Monster):
                    return
                self.has_vaulted = True
                self.speed = 1
                if landing_occupant is None:
                    self.board.move_entity(self, self.tile.row, landing_col)
                    return
                if isinstance(landing_occupant, Defense):
                    landing_occupant.take_damage(1)
                    if self.board.tiles[self.tile.row][landing_col].occupant is None:
                        self.board.move_entity(self, self.tile.row, landing_col)
                    return
                return
            if front_occupant is not None:
                return
            second_col = self.tile.col - 2
            if second_col < 0:
                self.board.trigger_end_state("Loss")
                return
            second_occupant = self.board.tiles[self.tile.row][second_col].occupant
            if second_occupant is None:
                self.board.move_entity(self, self.tile.row, second_col)
                return
            self.board.move_entity(self, self.tile.row, front_col)
            return
        super().act()

    def act_from_spawn_queue(self, board, row):
        entry_col = board.cols - 1
        occupant = board.tiles[row][entry_col].occupant
        if occupant is None:
            board.flush_entry_queue(row)
            return
        if not isinstance(occupant, Defense):
            return
        if not self.has_vaulted and isinstance(occupant, ForceWall):
            self.has_vaulted = True
            self.speed = 1
            return
        super().act_from_spawn_queue(board, row)

    def special_state(self):
        states = self.status_labels()
        if not self.has_vaulted:
            states.append("Jump ready")
        return ", ".join(states) if states else None


class Gargoyle(Monster):
    wave_cost = 5
    first_allowed_wave = 11
    pick_weight = 800

    def __init__(self):
        super().__init__(name="Gargoyle", hp=10)
        self.awakened = False
        self.pace_phase = 0

    def take_damage(self, amount):
        super().take_damage(amount)
        if self.board is not None and not self.awakened:
            self.awakened = True

    def should_skip_action(self):
        if super().should_skip_action():
            return True
        if self.awakened:
            return False
        if self.pace_phase == 0:
            self.pace_phase = 1
            return True
        self.pace_phase = 0
        return False

    def dormant_move(self):
        front_col = self.tile.col - 1
        if front_col < 0:
            self.board.trigger_end_state("Loss")
            return
        if self.board.tiles[self.tile.row][front_col].occupant is None:
            self.board.move_entity(self, self.tile.row, front_col)

    def charge_forward(self):
        current_col = self.tile.col
        furthest_reached_col = current_col
        attack_points = 3
        for step in range(1, 4):
            target_col = current_col - step
            if target_col < 0:
                self.board.trigger_end_state("Loss")
                return
            occupant = self.board.tiles[self.tile.row][target_col].occupant
            if occupant is None:
                furthest_reached_col = target_col
                continue
            while occupant.board is not None and attack_points > 0:
                occupant.take_damage(1)
                attack_points -= 1
            if self.board.tiles[self.tile.row][target_col].occupant is None:
                furthest_reached_col = target_col
                continue
            if furthest_reached_col != current_col:
                self.board.move_entity(self, self.tile.row, furthest_reached_col)
            return
        if furthest_reached_col != current_col:
            self.board.move_entity(self, self.tile.row, furthest_reached_col)

    def act(self):
        if not self.awakened:
            self.dormant_move()
            return
        self.charge_forward()

    def special_state(self):
        states = self.status_labels()
        states.append("Awakened" if self.awakened else "Dormant")
        return ", ".join(states)


class Necromancer(Skeleton):
    wave_cost = 5
    first_allowed_wave = 2
    pick_weight = 1100

    def __init__(self):
        super().__init__(name="Necromancer", hp=5, speed=1)
        self.pace_phase = 0
        self.action_count = 0

    def should_skip_action(self):
        if super().should_skip_action():
            return True
        if self.pace_phase == 0:
            self.pace_phase = 1
            return True
        self.pace_phase = 0
        return False

    def summon_backup(self):
        neighbors = (
            (self.tile.row - 1, self.tile.col),
            (self.tile.row, self.tile.col - 1),
            (self.tile.row + 1, self.tile.col),
            (self.tile.row, self.tile.col + 1),
        )
        for row, col in neighbors:
            if not (0 <= row < self.board.rows and 0 <= col < self.board.cols):
                continue
            if self.board.tiles[row][col].occupant is not None:
                continue
            backup = Skeleton()
            backup.spawn_turn = self.board.turn_count + 1
            backup.wave_number = self.wave_number
            backup.counts_toward_wave_health = False
            self.board.add_occupant(backup, row, col)

    def act(self):
        self.action_count += 1
        if self.action_count == 2 or (self.action_count > 2 and (self.action_count - 2) % 6 == 0):
            self.summon_backup()
        self.move_or_attack()

    def special_state(self):
        states = self.status_labels()
        next_summon_in = 2 - self.action_count if self.action_count < 2 else (6 - ((self.action_count - 2) % 6)) % 6
        if next_summon_in == 0:
            states.append("Summons now")
        else:
            states.append(f"Summons in {next_summon_in}")
        return ", ".join(states)


class Berserker(Skeleton):
    wave_cost = 2
    first_allowed_wave = 1
    pick_weight = 3200

    def __init__(self):
        super().__init__(name="Berserker", hp=6, speed=1)
        self.enraged = False

    def take_damage(self, amount):
        super().take_damage(amount)
        if self.board is not None and self.hp <= 3 and not self.enraged:
            self.enraged = True
            self.speed = 2
            self.attack_damage = 2

    def special_state(self):
        states = self.status_labels()
        if self.enraged:
            states.append("Enraged")
        return ", ".join(states) if states else None


class Golem(Monster):
    wave_cost = 9
    first_allowed_wave = 21
    pick_weight = 450

    def __init__(self):
        super().__init__(name="Golem", hp=36)
        self.speed = 1

    def shove_chain(self):
        target_col = self.tile.col - 1
        chain_cols = []
        scan_col = target_col
        while scan_col >= 0:
            occupant = self.board.tiles[self.tile.row][scan_col].occupant
            if not isinstance(occupant, Defense):
                break
            chain_cols.append(scan_col)
            scan_col -= 1
        if not chain_cols:
            return False
        chain_col_set = set(chain_cols)
        for col in chain_cols:
            destination_col = col - 1
            if destination_col < 0 or destination_col in chain_col_set:
                continue
            destination = self.board.tiles[self.tile.row][destination_col].occupant
            if isinstance(destination, Monster):
                return False
        for col in reversed(chain_cols):
            occupant = self.board.tiles[self.tile.row][col].occupant
            if occupant is None:
                continue
            if col == 0:
                occupant.die()
            else:
                self.board.move_entity(occupant, self.tile.row, col - 1)
        self.board.move_entity(self, self.tile.row, target_col)
        return True

    def act(self):
        target_col = self.tile.col - 1
        if target_col < 0:
            self.board.trigger_end_state("Loss")
            return
        occupant = self.board.tiles[self.tile.row][target_col].occupant
        if occupant is None:
            self.board.move_entity(self, self.tile.row, target_col)
            return
        if isinstance(occupant, Monster):
            return
        self.shove_chain()


class Juggernaut(Monster):
    wave_cost = 7
    first_allowed_wave = 3
    pick_weight = 650

    def __init__(self):
        super().__init__(name="Juggernaut", hp=20)
        self.speed = 2
        self.has_moved_once = False

    def act(self):
        current_col = self.tile.col
        path = []
        for step in range(1, self.speed + 1):
            target_col = current_col - step
            if target_col < 0:
                self.board.trigger_end_state("Loss")
                return
            path.append(target_col)

        for target_col in path:
            occupant = self.board.tiles[self.tile.row][target_col].occupant
            if occupant is not None:
                occupant.die()

        self.board.move_entity(self, self.tile.row, path[-1])
        if not self.has_moved_once:
            self.has_moved_once = True
            self.speed = 1

    def act_from_spawn_queue(self, board, row):
        entry_col = board.cols - 1
        occupant = board.tiles[row][entry_col].occupant
        if occupant is None:
            board.flush_entry_queue(row)
            return
        occupant.die()
        board.flush_entry_queue(row)

    def special_state(self):
        states = self.status_labels()
        if self.speed > 1:
            states.append("Fast")
        return ", ".join(states) if states else None

class MonsterSpawn:
    def __init__(self, monster_cls, count=1, row=None):
        self.monster_cls = monster_cls
        self.count = count
        self.row = row


class WaveConfig:
    def __init__(self, extra_points=0, scripted_spawns=()):
        self.extra_points = extra_points
        self.scripted_spawns = tuple(scripted_spawns)


class LevelDefinition:
    def __init__(
        self,
        name,
        rows,
        cols,
        defense_roster,
        monster_roster,
        total_waves,
        major_wave_interval,
        deployable_cols=None,
        wave_configs=None,
        first_wave_turn=4,
        turns_between_waves=6,
        starting_energy=0,
        ambient_energy_amount=0,
        ambient_energy_interval_turns=1,
        ambient_energy_per_turn=None,
        base_points_fn=None,
        level_setup=None,
        monster_rules=None,
    ):
        self.name = name
        self.rows = rows
        self.cols = cols
        if deployable_cols is None:
            deployable_cols = cols
        if not (1 <= deployable_cols <= cols):
            raise ValueError("deployable_cols must be between 1 and cols")
        self.deployable_cols = deployable_cols
        self.defense_roster = tuple(defense_roster)
        self.total_waves = total_waves
        self.major_wave_interval = major_wave_interval
        self.monster_roster = tuple(monster_roster)
        self.wave_configs = dict(wave_configs or {})
        self.first_wave_turn = first_wave_turn
        self.turns_between_waves = turns_between_waves
        self.starting_energy = starting_energy
        if ambient_energy_per_turn is not None:
            ambient_energy_amount = ambient_energy_per_turn
        self.ambient_energy_amount = ambient_energy_amount
        self.ambient_energy_interval_turns = ambient_energy_interval_turns
        self.base_points_fn = base_points_fn or (lambda wave_number: ((wave_number - 1) // 3) + 1)
        self.level_setup = level_setup
        self.monster_rules = dict(monster_rules or {})

    def is_major_wave(self, wave_number):
        return wave_number % self.major_wave_interval == 0

    def monster_first_allowed_wave(self, monster_cls):
        rule = self.monster_rules.get(monster_cls, {})
        return rule.get("first_allowed_wave", monster_cls.first_allowed_wave)

    def monster_pick_weight(self, monster_cls):
        rule = self.monster_rules.get(monster_cls, {})
        return rule.get("pick_weight", monster_cls.pick_weight)

    def build_wave(self, wave_number, rng):
        wave_config = self.wave_configs.get(wave_number, WaveConfig())
        planned_spawns = list(wave_config.scripted_spawns)
        remaining_points = self.base_points_fn(wave_number) + wave_config.extra_points

        for spawn in planned_spawns:
            remaining_points -= spawn.monster_cls.wave_cost * spawn.count

        while remaining_points > 0:
            candidates = [
                monster_cls for monster_cls in self.monster_roster
                if self.monster_pick_weight(monster_cls) > 0
                and self.monster_first_allowed_wave(monster_cls) <= wave_number
                and monster_cls.wave_cost <= remaining_points
            ]
            if not candidates:
                break
            weights = [self.monster_pick_weight(monster_cls) for monster_cls in candidates]
            monster_cls = rng.choices(candidates, weights=weights, k=1)[0]
            planned_spawns.append(MonsterSpawn(monster_cls))
            remaining_points -= monster_cls.wave_cost

        return planned_spawns

    def create_level(self, rng_seed=None):
        return Level(self, rng_seed=rng_seed)


class Level:
    def __init__(self, level_definition, rng_seed=None):
        self.definition = level_definition
        self.energy = level_definition.starting_energy
        self.board = Board(level_definition.rows, level_definition.cols)
        self.board.level = self
        self.deploy_client = DeployClient(self)
        self.clear_client = ClearClient(self)
        for defense_cls in level_definition.defense_roster:
            self.deploy_client.add_defense_class(defense_cls)
        if level_definition.level_setup:
            level_definition.level_setup(self)
        self.random = random.Random(rng_seed)
        self.spawned_waves = 0
        self.next_spawn_turn = level_definition.first_wave_turn
        self.current_wave_number = None
        self.current_wave_starting_health = 0

    @property
    def end_state(self):
        return self.board.end_state

    @property
    def turn_count(self):
        return self.board.turn_count

    def deploy_defense(self, defense_cls, row, col):
        return self.deploy_client.deploy_defense(defense_cls, row, col)

    def clear_defense(self, row, col):
        return self.clear_client.clear_defense(row, col)

    def pick_row(self, preferred_row=None):
        if preferred_row is not None:
            if 0 <= preferred_row < self.board.rows:
                return preferred_row
            return None

        return self.random.randrange(self.board.rows)

    def total_health_for_wave(self, wave_number):
        monsters = self.board.scan_entities(
            lambda occupant: (
                isinstance(occupant, Monster)
                and occupant.wave_number == wave_number
                and occupant.counts_toward_wave_health
            )
        )
        queued_health = 0
        for queue in self.board.entry_queues:
            for pending in queue:
                monster = pending["monster"]
                if monster.wave_number == wave_number and monster.counts_toward_wave_health:
                    queued_health += monster.hp
        return sum(monster.hp for monster in monsters) + queued_health

    def spawn_next_wave_if_ready(self):
        if self.spawned_waves >= self.definition.total_waves:
            return
        if self.board.turn_count + 1 < self.next_spawn_turn:
            return

        wave_number = self.spawned_waves + 1
        spawned_health = 0
        for spawn in self.definition.build_wave(wave_number, self.random):
            for _ in range(spawn.count):
                row = self.pick_row(spawn.row)
                if row is None:
                    return
                self.board.spawn_monster(spawn.monster_cls, row, wave_number=wave_number)
                spawned_health += spawn.monster_cls().hp

        self.spawned_waves = wave_number
        self.current_wave_number = wave_number
        self.current_wave_starting_health = spawned_health
        self.next_spawn_turn = self.board.turn_count + 1 + self.definition.turns_between_waves

    def update_spawn_timing(self):
        if self.current_wave_number is None:
            return
        if self.spawned_waves >= self.definition.total_waves:
            return
        if self.current_wave_starting_health <= 0:
            return

        current_health = self.total_health_for_wave(self.current_wave_number)
        if current_health * 2 < self.current_wave_starting_health:
            self.next_spawn_turn = min(self.next_spawn_turn, self.board.turn_count + 1)

    def update_end_state(self):
        if self.spawned_waves < self.definition.total_waves:
            return
        monsters_remaining = self.board.scan_entities(lambda occupant: isinstance(occupant, Monster))
        queued_monsters_remaining = any(self.board.entry_queues[row] for row in range(self.board.rows))
        if not monsters_remaining and not queued_monsters_remaining:
            self.board.trigger_end_state("Win")

    def run_turn(self):
        if self.end_state:
            return
        self.deploy_client.tick()
        self.spawn_next_wave_if_ready()
        resolved_turn = self.board.turn_count + 1
        if (
            self.definition.ambient_energy_amount > 0
            and self.definition.ambient_energy_interval_turns > 0
            and resolved_turn % self.definition.ambient_energy_interval_turns == 0
        ):
            self.energy += self.definition.ambient_energy_amount
        self.board.run_turn()
        self.update_spawn_timing()
        self.update_end_state()

    def to_ascii(self):
        return self.board.to_ascii()

    def state(self):
        next_wave = self.spawned_waves + 1
        if next_wave > self.definition.total_waves:
            next_wave_state = "All waves spawned"
        else:
            major_suffix = " (major wave)" if self.definition.is_major_wave(next_wave) else ""
            next_wave_state = f"Next wave: {next_wave}/{self.definition.total_waves}{major_suffix}"
        sections = []
        board_state = self.board.state()
        if board_state:
            sections.append(board_state)
        sections.append(f"Energy: {self.energy}")
        deploy_state = self.deploy_client.state()
        if deploy_state:
            sections.append(deploy_state)
        sections.extend([
            f"Level: {self.definition.name}",
            f"Waves spawned: {self.spawned_waves}/{self.definition.total_waves}",
            next_wave_state,
        ])
        return "\n".join(sections)

    def snapshot(self):
        next_wave_number = self.spawned_waves + 1
        if next_wave_number > self.definition.total_waves:
            next_wave_number = None
            next_wave_is_major = False
        else:
            next_wave_is_major = self.definition.is_major_wave(next_wave_number)
        return {
            "level_name": self.definition.name,
            "turn_count": self.turn_count,
            "energy": self.energy,
            "spawned_waves": self.spawned_waves,
            "total_waves": self.definition.total_waves,
            "next_wave_number": next_wave_number,
            "next_wave_is_major": next_wave_is_major,
            "end_state": self.end_state,
        }

    def replay_snapshot(self):
        occupants = []
        for row in self.board.tiles:
            for tile in row:
                occupant = tile.occupant
                if occupant is None:
                    continue
                entry = {
                    "row": tile.row,
                    "col": tile.col,
                    "class_name": type(occupant).__name__,
                    "kind": "defense" if isinstance(occupant, Defense) else "monster",
                    "name": occupant.name,
                    "hp": occupant.hp,
                    "special_state": occupant.special_state(),
                }
                if isinstance(occupant, Monster):
                    entry["wave_number"] = occupant.wave_number
                    entry["skip_next_action"] = occupant.skip_next_action
                    entry["counts_toward_wave_health"] = occupant.counts_toward_wave_health
                if hasattr(occupant, "turns_to_generate"):
                    entry["turns_to_generate"] = occupant.turns_to_generate
                if hasattr(occupant, "turns_to_arm"):
                    entry["turns_to_arm"] = occupant.turns_to_arm
                if hasattr(occupant, "turns_to_digest"):
                    entry["turns_to_digest"] = occupant.turns_to_digest
                if hasattr(occupant, "ready_to_fire"):
                    entry["ready_to_fire"] = occupant.ready_to_fire
                if hasattr(occupant, "has_vaulted"):
                    entry["has_vaulted"] = occupant.has_vaulted
                if hasattr(occupant, "pace_phase"):
                    entry["pace_phase"] = occupant.pace_phase
                if hasattr(occupant, "action_count"):
                    entry["action_count"] = occupant.action_count
                if hasattr(occupant, "enraged"):
                    entry["enraged"] = occupant.enraged
                if hasattr(occupant, "awakened"):
                    entry["awakened"] = occupant.awakened
                if hasattr(occupant, "move_phase"):
                    entry["move_phase"] = occupant.move_phase
                if hasattr(occupant, "speed"):
                    entry["speed"] = occupant.speed
                if hasattr(occupant, "attack_damage"):
                    entry["attack_damage"] = occupant.attack_damage
                if hasattr(occupant, "has_moved_once"):
                    entry["has_moved_once"] = occupant.has_moved_once
                if hasattr(occupant, "frozen_turns"):
                    entry["frozen_turns"] = occupant.frozen_turns
                if hasattr(occupant, "chilled"):
                    entry["chilled"] = occupant.chilled
                if hasattr(occupant, "chill_phase"):
                    entry["chill_phase"] = occupant.chill_phase
                occupants.append(entry)

        return {
            "level_name": self.definition.name,
            "rows": self.definition.rows,
            "cols": self.definition.cols,
            "deployable_cols": self.definition.deployable_cols,
            "turn_count": self.turn_count,
            "energy": self.energy,
            "spawned_waves": self.spawned_waves,
            "total_waves": self.definition.total_waves,
            "major_wave_interval": self.definition.major_wave_interval,
            "end_state": self.end_state,
            "defense_roster": [defense_cls.__name__ for defense_cls in self.definition.defense_roster],
            "cooldowns": {
                defense_cls.__name__: self.deploy_client.cooldowns.get(defense_cls, 0)
                for defense_cls in self.definition.defense_roster
            },
            "occupants": occupants,
        }

    def available_defense_statuses(self):
        statuses = []
        for defense_cls in self.definition.defense_roster:
            cooldown_remaining = self.deploy_client.cooldowns.get(defense_cls, 0)
            statuses.append({
                "name": defense_cls.__name__,
                "cost": defense_cls.cost,
                "cooldown_remaining": cooldown_remaining,
                "ready": cooldown_remaining == 0 and self.energy >= defense_cls.cost,
            })
        return statuses

    def describe_tile(self, row, col):
        occupant = self.board.tiles[row][col].occupant
        if occupant is None:
            return {
                "empty": True,
                "row": row,
                "col": col,
                "deployable": self.board.is_deployable_col(col),
                "entry_column": self.board.is_entry_column(col),
                "occupant": None,
            }

        description = {
            "empty": False,
            "row": row,
            "col": col,
            "deployable": self.board.is_deployable_col(col),
            "entry_column": self.board.is_entry_column(col),
            "occupant": {
                "kind": "defense" if isinstance(occupant, Defense) else "monster",
                "name": occupant.name,
                "hp": occupant.hp,
                "special_state": occupant.special_state(),
            },
        }
        if isinstance(occupant, Monster):
            description["occupant"]["wave_number"] = occupant.wave_number
        return description


def calculate_level_score(total_waves, reached_waves, end_state):
    if end_state == "Win":
        return 1.0
    if end_state != "Loss" or total_waves <= 0:
        return None
    reached_waves = max(0, min(reached_waves, total_waves))
    progress = reached_waves / total_waves
    return 0.5 * (progress ** 2)


def score_summary_from_progress(total_waves, reached_waves, end_state):
    bounded_waves = 0 if total_waves <= 0 else max(0, min(reached_waves, total_waves))
    return {
        "score": calculate_level_score(total_waves, reached_waves, end_state),
        "outcome": end_state,
        "reached_waves": bounded_waves,
        "total_waves": total_waves,
        "completed": end_state in {"Win", "Loss"},
    }


def score_summary_from_snapshot(snapshot):
    return score_summary_from_progress(
        total_waves=snapshot["total_waves"],
        reached_waves=snapshot["spawned_waves"],
        end_state=snapshot["end_state"],
    )


def score_summary_from_level(level):
    return score_summary_from_progress(
        total_waves=level.definition.total_waves,
        reached_waves=level.spawned_waves,
        end_state=level.end_state,
    )

def make_level_1_definition():
    return LevelDefinition(
        name="Level 1",
        rows=5,
        cols=10,
        deployable_cols=9,
        defense_roster=(Turret, PowerPlant, Barricade, Grenade, LandMine),
        monster_roster=(Skeleton, Goblin, Orc),
        total_waves=10,
        major_wave_interval=10,
        wave_configs={
            4: WaveConfig(extra_points=1),
            5: WaveConfig(extra_points=1),
            6: WaveConfig(extra_points=2),
            7: WaveConfig(extra_points=2),
            8: WaveConfig(extra_points=3),
            9: WaveConfig(extra_points=3),
            10: WaveConfig(
                extra_points=8,
                scripted_spawns=(
                    MonsterSpawn(Skeleton, count=4),
                    MonsterSpawn(Herald),
                    MonsterSpawn(Goblin),
                ),
            ),
        },
        starting_energy=2,
        ambient_energy_amount=1,
        ambient_energy_interval_turns=2,
    )


def make_level_2_definition():
    return LevelDefinition(
        name="Level 2",
        rows=5,
        cols=10,
        deployable_cols=9,
        defense_roster=(PowerPlant, Turret, IceTurret, DoubleTurret, Crusher, Barricade),
        monster_roster=(Skeleton, Leaper, Goblin, Orc),
        total_waves=20,
        major_wave_interval=10,
        wave_configs={
            4: WaveConfig(extra_points=1),
            5: WaveConfig(extra_points=1),
            6: WaveConfig(extra_points=2, scripted_spawns=(MonsterSpawn(Leaper),)),
            7: WaveConfig(extra_points=2),
            8: WaveConfig(extra_points=3, scripted_spawns=(MonsterSpawn(Leaper),)),
            9: WaveConfig(extra_points=4, scripted_spawns=(MonsterSpawn(Goblin),)),
            10: WaveConfig(
                extra_points=7,
                scripted_spawns=(
                    MonsterSpawn(Skeleton, count=4),
                    MonsterSpawn(Leaper, count=2),
                    MonsterSpawn(Goblin),
                    MonsterSpawn(Herald),
                ),
            ),
            11: WaveConfig(extra_points=2),
            12: WaveConfig(extra_points=3, scripted_spawns=(MonsterSpawn(Leaper),)),
            13: WaveConfig(extra_points=4, scripted_spawns=(MonsterSpawn(Goblin),)),
            14: WaveConfig(extra_points=4, scripted_spawns=(MonsterSpawn(Leaper, count=2),)),
            15: WaveConfig(extra_points=5, scripted_spawns=(MonsterSpawn(Orc),)),
            16: WaveConfig(extra_points=5, scripted_spawns=(MonsterSpawn(Leaper), MonsterSpawn(Goblin))),
            17: WaveConfig(extra_points=6, scripted_spawns=(MonsterSpawn(Orc),)),
            18: WaveConfig(extra_points=7, scripted_spawns=(MonsterSpawn(Leaper, count=2), MonsterSpawn(Goblin))),
            19: WaveConfig(extra_points=8, scripted_spawns=(MonsterSpawn(Orc), MonsterSpawn(Goblin))),
            20: WaveConfig(
                extra_points=14,
                scripted_spawns=(
                    MonsterSpawn(Skeleton, count=5),
                    MonsterSpawn(Leaper, count=3),
                    MonsterSpawn(Goblin, count=2),
                    MonsterSpawn(Orc, count=2),
                    MonsterSpawn(Herald),
                ),
            ),
        },
        first_wave_turn=4,
        turns_between_waves=6,
        starting_energy=2,
        ambient_energy_amount=1,
        ambient_energy_interval_turns=2,
        base_points_fn=lambda wave_number: 1 + ((wave_number - 1) // 2),
    )


def level_3_base_points(wave_number):
    if wave_number <= 19:
        return 1 + ((wave_number - 1) // 2)
    if wave_number <= 25:
        return 11
    return 12


def make_level_3_definition():
    return LevelDefinition(
        name="Level 3",
        rows=5,
        cols=10,
        deployable_cols=9,
        defense_roster=(PowerPlant, Backstabber, IceTurret, Cannon, LineBomb, ForceWall, AcidSprayer),
        monster_roster=(Skeleton, Herald, Leaper, Necromancer, Berserker, Juggernaut),
        total_waves=30,
        major_wave_interval=10,
        wave_configs={
            4: WaveConfig(extra_points=1),
            5: WaveConfig(extra_points=1),
            6: WaveConfig(extra_points=2, scripted_spawns=(MonsterSpawn(Berserker),)),
            7: WaveConfig(extra_points=2),
            8: WaveConfig(extra_points=3, scripted_spawns=(MonsterSpawn(Leaper),)),
            9: WaveConfig(extra_points=4, scripted_spawns=(MonsterSpawn(Berserker),)),
            10: WaveConfig(
                extra_points=10,
                scripted_spawns=(
                    MonsterSpawn(Herald),
                    MonsterSpawn(Necromancer),
                    MonsterSpawn(Leaper),
                    MonsterSpawn(Berserker),
                ),
            ),
            11: WaveConfig(extra_points=2),
            12: WaveConfig(extra_points=3),
            13: WaveConfig(extra_points=4, scripted_spawns=(MonsterSpawn(Berserker),)),
            14: WaveConfig(extra_points=4, scripted_spawns=(MonsterSpawn(Leaper),)),
            15: WaveConfig(extra_points=5, scripted_spawns=(MonsterSpawn(Necromancer),)),
            16: WaveConfig(extra_points=6, scripted_spawns=(MonsterSpawn(Leaper),)),
            17: WaveConfig(extra_points=6, scripted_spawns=(MonsterSpawn(Berserker),)),
            18: WaveConfig(extra_points=7, scripted_spawns=(MonsterSpawn(Necromancer),)),
            19: WaveConfig(extra_points=8, scripted_spawns=(MonsterSpawn(Juggernaut),)),
            20: WaveConfig(
                extra_points=14,
                scripted_spawns=(
                    MonsterSpawn(Herald),
                    MonsterSpawn(Necromancer),
                    MonsterSpawn(Berserker, count=2),
                    MonsterSpawn(Juggernaut),
                ),
            ),
            21: WaveConfig(extra_points=3),
            22: WaveConfig(extra_points=4),
            23: WaveConfig(extra_points=5, scripted_spawns=(MonsterSpawn(Necromancer),)),
            24: WaveConfig(extra_points=6),
            25: WaveConfig(extra_points=7, scripted_spawns=(MonsterSpawn(Juggernaut),)),
            26: WaveConfig(extra_points=8, scripted_spawns=(MonsterSpawn(Necromancer),)),
            27: WaveConfig(extra_points=9, scripted_spawns=(MonsterSpawn(Berserker), MonsterSpawn(Juggernaut))),
            28: WaveConfig(extra_points=10, scripted_spawns=(MonsterSpawn(Necromancer),)),
            29: WaveConfig(extra_points=11, scripted_spawns=(MonsterSpawn(Juggernaut), MonsterSpawn(Leaper))),
            30: WaveConfig(
                extra_points=18,
                scripted_spawns=(
                    MonsterSpawn(Herald),
                    MonsterSpawn(Necromancer, count=2),
                    MonsterSpawn(Berserker, count=2),
                    MonsterSpawn(Juggernaut),
                    MonsterSpawn(Leaper, count=2),
                ),
            ),
        },
        first_wave_turn=4,
        turns_between_waves=6,
        starting_energy=2,
        ambient_energy_amount=1,
        ambient_energy_interval_turns=2,
        base_points_fn=level_3_base_points,
    )


def make_level_4_definition():
    return LevelDefinition(
        name="Level 4",
        rows=5,
        cols=10,
        deployable_cols=9,
        defense_roster=(QuadTurret, PowerPlant, Vortex, Barricade, Crusher, Grenade, FreezeMine),
        monster_roster=(Skeleton, Herald, Imp, Necromancer, Gargoyle, Golem),
        total_waves=30,
        major_wave_interval=10,
        wave_configs={
            4: WaveConfig(extra_points=1),
            5: WaveConfig(extra_points=1),
            6: WaveConfig(extra_points=2, scripted_spawns=(MonsterSpawn(Imp),)),
            7: WaveConfig(extra_points=2),
            8: WaveConfig(extra_points=3, scripted_spawns=(MonsterSpawn(Imp),)),
            9: WaveConfig(extra_points=4, scripted_spawns=(MonsterSpawn(Imp),)),
            10: WaveConfig(
                extra_points=10,
                scripted_spawns=(
                    MonsterSpawn(Herald),
                    MonsterSpawn(Imp, count=2),
                ),
            ),
            11: WaveConfig(extra_points=2),
            12: WaveConfig(extra_points=3, scripted_spawns=(MonsterSpawn(Necromancer),)),
            13: WaveConfig(extra_points=4, scripted_spawns=(MonsterSpawn(Gargoyle),)),
            14: WaveConfig(extra_points=4, scripted_spawns=(MonsterSpawn(Imp),)),
            15: WaveConfig(extra_points=5, scripted_spawns=(MonsterSpawn(Necromancer),)),
            16: WaveConfig(extra_points=6, scripted_spawns=(MonsterSpawn(Gargoyle),)),
            17: WaveConfig(extra_points=6, scripted_spawns=(MonsterSpawn(Imp), MonsterSpawn(Necromancer))),
            18: WaveConfig(extra_points=7, scripted_spawns=(MonsterSpawn(Gargoyle),)),
            19: WaveConfig(extra_points=8, scripted_spawns=(MonsterSpawn(Necromancer), MonsterSpawn(Imp))),
            20: WaveConfig(
                extra_points=14,
                scripted_spawns=(
                    MonsterSpawn(Herald),
                    MonsterSpawn(Necromancer),
                    MonsterSpawn(Gargoyle),
                ),
            ),
            21: WaveConfig(extra_points=3),
            22: WaveConfig(extra_points=4, scripted_spawns=(MonsterSpawn(Golem),)),
            23: WaveConfig(extra_points=5, scripted_spawns=(MonsterSpawn(Necromancer),)),
            24: WaveConfig(extra_points=6, scripted_spawns=(MonsterSpawn(Gargoyle),)),
            25: WaveConfig(extra_points=7, scripted_spawns=(MonsterSpawn(Golem),)),
            26: WaveConfig(extra_points=8, scripted_spawns=(MonsterSpawn(Golem), MonsterSpawn(Imp))),
            27: WaveConfig(extra_points=9, scripted_spawns=(MonsterSpawn(Necromancer), MonsterSpawn(Gargoyle))),
            28: WaveConfig(extra_points=10, scripted_spawns=(MonsterSpawn(Golem),)),
            29: WaveConfig(extra_points=11, scripted_spawns=(MonsterSpawn(Gargoyle), MonsterSpawn(Imp))),
            30: WaveConfig(
                extra_points=18,
                scripted_spawns=(
                    MonsterSpawn(Herald),
                    MonsterSpawn(Necromancer),
                    MonsterSpawn(Gargoyle),
                    MonsterSpawn(Golem),
                ),
            ),
        },
        first_wave_turn=4,
        turns_between_waves=6,
        starting_energy=2,
        ambient_energy_amount=1,
        ambient_energy_interval_turns=2,
        base_points_fn=level_3_base_points,
        monster_rules={
            Necromancer: {"first_allowed_wave": 11, "pick_weight": 900},
        },
    )


LEVEL_BUILDERS = {
    1: make_level_1_definition,
    2: make_level_2_definition,
    3: make_level_3_definition,
    4: make_level_4_definition,
}


def available_level_ids():
    return tuple(sorted(LEVEL_BUILDERS))


def get_level_definition(level_id):
    try:
        return LEVEL_BUILDERS[level_id]()
    except KeyError as exc:
        raise ValueError(f"Unknown level: {level_id}") from exc


def create_level(level_id=1, rng_seed=None):
    return get_level_definition(level_id).create_level(rng_seed=rng_seed)


def make_simple_10_wave_level():
    return make_level_1_definition()


def build_demo_level(level_id=1, seed=7):
    return create_level(level_id=level_id, rng_seed=seed)


if __name__ == "__main__":
    level = build_demo_level()
    print(level.to_ascii())
    for _ in range(12):
        print(f"Turn {level.turn_count}")
        if level.end_state:
            print(f"Game ended with state: {level.end_state}")
            print("Final Board State:")
            print(level.state())
            print("Final ASCII representation:")
            print(level.to_ascii())
            break

        print("Board State:")
        print(level.state())
        print("ASCII representation:")
        print(level.to_ascii())
        level.run_turn()
