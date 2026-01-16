import mesa
import random

SMOKE_TOLERANCE_STEPS = 3.0
SMOKE_DEATH_THRESHOLD = 7.0
HEAT_DAMAGE_THRESHOLD = 4.0
HEAT_DEATH_THRESHOLD = 8.0


class ExitAgent(mesa.Agent):
    def __init__(self, unique_id, model):
        super().__init__(model)
        self.unique_id = unique_id

class WallAgent(mesa.Agent):
    def __init__(self, unique_id, model):
        super().__init__(model)
        self.unique_id = unique_id

class StairAgent(mesa.Agent):
    def __init__(self, unique_id, model):
        super().__init__(model)
        self.unique_id = unique_id

class SmokeAgent(mesa.Agent):
    def __init__(self, unique_id, model):
        super().__init__(model)
        self.unique_id = unique_id

class VentilationAgent(mesa.Agent):
    def __init__(self, unique_id, model):
        super().__init__(model)
        self.unique_id = unique_id

class AlarmAgent(mesa.Agent):
    def __init__(self, unique_id, model, floor, position, radius=6):
        super().__init__(model)
        self.unique_id = unique_id
        self.floor = floor
        self.position = position
        self.radius = radius

        self.state = "idle"
        self.detect_timer = 0

        self.DETECTION_DELAY = 3
        self.ACTIVATION_DELAY = 5

    @property
    def active(self):
        return self.state == "active"

    def step(self):
        grid = self.model.grids[self.floor]

        smoke_nearby = False
        for pos in grid.get_neighborhood(self.position, moore=True, radius=self.radius):
            if any(isinstance(a, SmokeAgent) for a in grid.get_cell_list_contents(pos)):
                smoke_nearby = True
                break

        if self.state == "idle":
            if smoke_nearby:
                self.state = "detected"
                self.detect_timer = 0

        elif self.state == "detected":
            if smoke_nearby:
                self.detect_timer += 1
                if self.detect_timer >= self.DETECTION_DELAY:
                    self.state = "activating"
                    self.detect_timer = 0
            else:
                self.state = "idle"
                self.detect_timer = 0

        elif self.state == "activating":
            self.detect_timer += 1
            if self.detect_timer >= self.ACTIVATION_DELAY:
                self.state = "active"



class EvacueeAgent(mesa.Agent):
    def __init__(self, unique_id, model):
        super().__init__(model)
        self.unique_id = unique_id
        self.speed = random.uniform(
            self.model.min_speed,
            self.model.max_speed
        )

        # statusi
        self.dead = False
        self.evacuated = False
        self.panic = random.uniform(0.0, 0.3) # početna panika

        self.smoke_steps = 0

        self.spawn_step = model.steps
        self.evacuated_step = None
        self.evacuation_time = None

        self.last_exit_dist = None
        self.stuck_steps = 0

        self.visible_cells = set()
        self.vision_range = 5
        self.blocked_cells = set()

        self.alarm_heard = False

        self.strategy = random.choice([
            "shortest",
            "safest",
            "least_crowded"
        ])

    def die(self):
        if self.dead:
            return

        self.dead = True
        self.model.dead_count += 1
        print(f"Agent {self.unique_id} je poginuo u dimu")

        self.model.grids[self.floor].remove_agent(self)

    def evacuate(self):
        if self.evacuated or self.dead:
            return

        self.evacuated = True
        self.evacuated_step = self.model.steps
        self.evacuation_time = self.evacuated_step - self.spawn_step

        self.model.evacuated_count += 1
        self.model.evacuation_times.append(self.evacuation_time)

        exit_key = (self.floor, self.pos[0], self.pos[1])
        exit_info = self.model.exit_info.get(exit_key)
        exit_id = exit_info["id"] if exit_info else "Unknown"
        print(
            f"EVAKUIRAN agent {self.unique_id} | izlaz: {exit_id} | vrijeme evakuacije: {self.evacuation_time} | ukupno evakuiranih: {self.model.evacuated_count}"
        )

        self.model.grids[self.floor].remove_agent(self)

    def panic_update(self):
        self.panic = min(1.0, self.panic + 0.02)

        grid = self.model.grids[self.floor]

        neighboors = grid.get_neighborhood(self.pos, moore=True, include_center=False)
        if any(
            any(isinstance(a, SmokeAgent)for a in grid.get_cell_list_contents(n))
                for n in neighboors
        ):
            self.panic = min(1.0, self.panic + 0.05)

    def adapt_strategy(self):
        if self.stuck_steps >= 5:
            self.strategy = "least_crowded"
            self.panic = min(1.0, self.panic + 0.15)
            return

        if self.panic > 0.7:
            self.strategy = "shortest"
            return

        if self.panic > 0.5:
            self.strategy = "least_crowded"
            return

        if self.panic >= 0.2:
            self.strategy = "safest"
            return
        
        self.strategy = random.choice(["shortest", "least_crowded", "safest"])

    def receive_message(self, performative, content):
        """Simulacija FIPA-ACL primanja poruke"""
        if performative == "INFORM":
            if content["type"] == "fire_detected":
                # agent dodaje lolaciju vatre u svoju bazu  znanja jer je dobio poruku
                self.blocked_cells.add(content["location"])
                self.panic = min(1.0, self.panic + 0.1) # obavijest da se dim širi

    def step(self):
        if self.dead or self.evacuated or self.pos is None:
            return

        if self.alarm_heard:
            self.panic = min(1.0, self.panic + 0.05)

        self.perceive_environment()

        grid = self.model.grids[self.floor]

        self.panic_update()

        dist = self.model.distance_to_nearest_exit(self.floor, self.pos)

        if self.last_exit_dist is not None and dist is not None:
            if dist > self.last_exit_dist:
                self.stuck_steps += 1
            else:
                self.stuck_steps = 0

        self.last_exit_dist = dist

        if dist is not None and dist <= 3:
            self.panic = min(self.panic, 0.4)


        cell_heat = self.model.heat[self.floor][self.pos]
        has_smoke = any(isinstance(a, SmokeAgent) for a in grid.get_cell_list_contents(self.pos))

        if has_smoke or cell_heat > HEAT_DAMAGE_THRESHOLD:
            heat_multiplier = 1.0 + max(0, (cell_heat - HEAT_DAMAGE_THRESHOLD) / 10.0)
            self.smoke_steps += heat_multiplier

            if cell_heat >= HEAT_DEATH_THRESHOLD:
                print(f"Agent {self.unique_id} je umro od ekstremne topline ({cell_heat:.1f}°)")
                self.die()
                return

            if self.smoke_steps >= SMOKE_DEATH_THRESHOLD:
                print(f"Agent {self.unique_id} je umro od dugotrajne izloženosti dimu/toplini (akumulirana šteta: {self.smoke_steps:.1f})")
                self.die()
                return

            if self.smoke_steps > SMOKE_TOLERANCE_STEPS:
                panic_increase = 0.08 + (self.smoke_steps - SMOKE_TOLERANCE_STEPS) * 0.02
                self.panic = min(1.0, self.panic + panic_increase)
            else:
                self.panic = min(1.0, self.panic + 0.05)

        else:
            if self.smoke_steps > 0:

                self.smoke_steps = max(0, self.smoke_steps - 0.5)

        # evakuacija
        exit_key = (self.floor, self.pos[0], self.pos[1])
        if exit_key in self.model.exits:
            if self.model.request_exit_pass(exit_key):
                self.evacuate()
            else:
                self.panic = min(1.0, self.panic + 0.03)
            return

        effective_speed = min(1.0, self.speed + self.panic * 0.3)
        if random.random() > effective_speed:
            return

        self.adapt_strategy()

        result = self.model.dijkstra_next_step(self.floor, self.pos, self)
        if result is None:
            return

        _, next_pos = result

        # teleportacija preko stepenica
        stair_key = (self.floor, next_pos[0], next_pos[1])
        if stair_key in self.model.stair_links:
            target_floor = self.model.stair_links[stair_key]

            if not self.model.passable(target_floor, next_pos, self):
                return

            grid.remove_agent(self)

            self.floor = target_floor
            self.model.grids[target_floor].place_agent(self, next_pos)

            self.panic = min(1.0, self.panic + 0.05)
            return

        grid.move_agent(self, next_pos)

    def perceive_environment(self):
        if self.pos is None:
            return

        grid = self.model.grids[self.floor]
        self.visible_cells.clear()

        sent_fire_msg = False

        for dx in range(-self.vision_range, self.vision_range + 1):
            for dy in range(-self.vision_range, self.vision_range + 1):
                x = self.pos[0] + dx
                y = self.pos[1] + dy
                if not (0 <= x < grid.width and 0 <= y < grid.height):
                    continue

                self.visible_cells.add((self.floor, x, y))

                if any(isinstance(a, SmokeAgent) for a in grid.get_cell_list_contents((x, y))):
                    loc = (self.floor, x, y)
                    self.blocked_cells.add(loc)

                    if not sent_fire_msg:
                        neighbor_positions = grid.get_neighborhood(self.pos, moore=True, radius=2, include_center=False)
                        for neighbor_pos in neighbor_positions:
                            for neighbor in grid.get_cell_list_contents(neighbor_pos):
                                if isinstance(neighbor, EvacueeAgent) and neighbor is not self:
                                    neighbor.receive_message(
                                        "INFORM",
                                        {"type": "fire_detected", "location": loc, "from": self.unique_id}
                                    )
                        sent_fire_msg = True

        to_remove = set()

        for (f, x, y) in self.blocked_cells:
            if not any(
                isinstance(a, SmokeAgent)
                for a in self.model.grids[f].get_cell_list_contents((x, y))
            ):
                to_remove.add((f, x, y))

        self.blocked_cells -= to_remove