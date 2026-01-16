import json
import heapq
from mesa import Model
from mesa.space import MultiGrid

try:
    from model.agent import EvacueeAgent, WallAgent, ExitAgent, StairAgent, SmokeAgent, VentilationAgent, AlarmAgent
except ImportError:
    from agent import EvacueeAgent, WallAgent, ExitAgent, StairAgent, SmokeAgent, VentilationAgent, AlarmAgent


class EvaluationModel(Model):

    def __init__(self, layout_path="podaci/building_layout.json"):
        super().__init__()
        self.running = True
        self.steps = 0
        self.id_counter = 0
        self.evacuated_count = 0
        self.dead_count = 0
        self.evacuation_times = []

        self.smoke_spread_prob = 0.15
        self.smoke_spread_moore = False

        self.room_doors = {}

        self.history = {
            "steps" : [],
            "evacuated" : [],
            "dead" : []
        }

        # učitavnanje layouta
        with open(layout_path, "r") as f:
            layout = json.load(f)

        floor0 = layout["floors"][0]
        self.width = floor0["dimensions"]["width"]
        self.height = floor0["dimensions"]["height"]

        people_cfg = layout.get("people", {})
        speed_cfg = people_cfg.get("speed", {})

        self.min_speed = speed_cfg.get("min", 0.5)
        self.max_speed = speed_cfg.get("max", 1.0)

        self.grids = {}
        self.floors = {}

        for floor in layout["floors"]:
            fid = floor["floor_id"]
            w = floor["dimensions"]["width"]
            h = floor["dimensions"]["height"]
            self.grids[fid] = MultiGrid(w, h, torus=False)
            self.floors[fid] = floor

        self.heat = {}

        for fid, grid in self.grids.items():
            self.heat[fid] = {
                (x, y): 0.0
                for x in range(grid.width)
                for y in range(grid.height)
            }

        self.active_floor = 0
        self.grid = self.grids[self.active_floor]

        self.walls = set()
        self.exits = set()
        self.final_exits = set()
        self.exit_info = {}
        self.exit_flow_total = {}
        self.exit_flow_step = {}
        self.exit_flow_history = {}
        self.exit_queue_history = {}

        self.corridor_cells = set()
        self.stair_links = {}

        # vanjski zidovi
        for fid, floor in self.floors.items():
            w = self.grids[fid].width
            h = self.grids[fid].height

            for x in range(w):
                self.walls.add((fid, x, 0))
                self.walls.add((fid, x, h - 1))
            for y in range(h):
                self.walls.add((fid, 0, y))
                self.walls.add((fid, w - 1, y))


        # ventilacija
        self.ventilation_cells = set()

        for v in layout.get("ventilation", []):
            fid = v["floor"]
            x = v["x"]
            y = v["y"]

            self.ventilation_cells.add((fid, x, y))
            a = VentilationAgent(self.next_id(), self)
            self.grids[fid].place_agent(a, (x, y))
            self.agents.add(a)

        for fid, floor in self.floors.items():
            for corridor in floor.get("corridors", []):
                path = corridor.get("path", [])
                width = int(corridor.get("width", 1))
                half = width // 2

                for p in path:
                    cx, cy = p["x"], p["y"]

                    for dx in range(-half, half + 1):
                        for dy in range(-half, half + 1):
                            x, y = cx + dx, cy + dy
                            if 0 <= x < self.grids[fid].width and 0 <= y < self.grids[fid].height:
                                self.corridor_cells.add((fid, x, y))
                                self.walls.discard((fid, x, y))

        self.alarms = []

        # alarmi
        for alarm_data in layout.get("alarms", []):
            fid = alarm_data["floor"]
            x = alarm_data["x"]
            y = alarm_data["y"]
            radius = alarm_data.get("radius", 13)

            alarm = AlarmAgent(
                self.next_id(),
                self,
                floor=fid,
                position=(x, y),
                radius=radius
            )

            self.grids[fid].place_agent(alarm, alarm.position)
            self.agents.add(alarm)
            self.alarms.append(alarm)

        # hodnici
        for fid, floor in self.floors.items():
           for room in floor.get("rooms", []):
               rid = room["id"]
               self.room_doors[(fid, rid)] = [(d["x"], d["y"]) for d in room.get("doors", [])]

        for floor in layout["floors"]:
            fid = floor["floor_id"]
            for exit_data in floor.get("exits", []):
                x = exit_data["position"]["x"]
                y = exit_data["position"]["y"]

                exit_id = exit_data.get("id", f"exit_{fid}_{x}_{y}")
                capacity = int(exit_data.get("capacity", 999999))
                width = int(exit_data.get("width", 1))

                exit_key = (fid, x, y)

                self.exits.add(exit_key)
                self.walls.discard(exit_key)

                if fid == 0:
                    self.final_exits.add(exit_key)

                self.exit_info[exit_key] = {"id": exit_id,
                                            "capacity": capacity,
                                            "width": width}
                self.exit_flow_total[exit_key] = 0
                self.exit_flow_step[exit_key] = 0
                self.exit_flow_history[exit_key] = []
                self.exit_queue_history[exit_key] = []

                a = ExitAgent(self.next_id(), self)
                a.floor = fid
                self.grids[fid].place_agent(a, (x, y))
                self.agents.add(a)

        # steoenice
        for fid, floor in self.floors.items():
            for stair_data in floor.get("stairs", []):
                sx = stair_data["position"]["x"]
                sy = stair_data["position"]["y"]
                target_fid = stair_data["connects_to_floor"]

                stair = StairAgent(self.next_id(), self)
                stair.floor = fid
                stair.connects_to_floor = target_fid

                self.grids[fid].place_agent(stair, (sx, sy))
                self.agents.add(stair)

                self.stair_links[(fid, sx, sy)] = target_fid

                self.walls.discard((fid, sx, sy))

        # prostorije
        for fid, floor in self.floors.items():
            grid = self.grids[fid]

            for room in floor.get("rooms", []):
                b = room["bounds"]

                # zidovi od prostorije
                for x in range(b["x"], b["x"] + b["width"]):
                    for y in range(b["y"], b["y"] + b["height"]):
                        is_edge = (
                            x == b["x"]
                            or x == b["x"] + b["width"] - 1
                            or y == b["y"]
                            or y == b["y"] + b["height"] - 1
                        )
                        if is_edge and (fid, x, y) not in self.corridor_cells:
                            self.walls.add((fid, x, y))

               # vrata
                for door in room.get("doors", []):
                    dx, dy = door["x"], door["y"]
                    self.walls.discard((fid, dx, dy))

                for x in range(b["x"], b["x"] + b["width"]):
                    for y in range(b["y"], b["y"] + b["height"]):
                        if (fid, x, y) in self.walls and (fid, x, y) not in self.exits:
                            if grid.is_cell_empty((x, y)):
                                w_agent = WallAgent(self.next_id(), self)
                                w_agent.floor = fid
                                grid.place_agent(w_agent, (x, y))
                                self.agents.add(w_agent)

                # postavi osobe u prostorije
                max_occ = room.get("max_occupancy", 0)
                placed = 0
                attempts = 0

                while placed < max_occ and attempts < 500:
                    if b["width"] <= 2 or b["height"] <= 2:
                        break

                    rx = self.random.randint(b["x"] + 1, b["x"] + b["width"] - 2)
                    ry = self.random.randint(b["y"] + 1, b["y"] + b["height"] - 2)
                    pos = (rx, ry)

                    # izbjegni zidove
                    if (fid, rx, ry) in self.walls or (fid, rx, ry) in self.exits:
                        attempts += 1
                        continue

                    # provjeri da u ćelijama nema drugih ljudi i da nema dima
                    if grid.is_cell_empty(pos) and not any(
                        isinstance(a, SmokeAgent) for a in grid.get_cell_list_contents(pos)
                    ):
                        e = EvacueeAgent(self.next_id(), self)
                        e.floor = fid
                        grid.place_agent(e, pos)
                        self.agents.add(e)
                        placed += 1

                    attempts += 1

        corridor_spawn_ratio = 0.25

        total_people = sum(
            room.get("max_occupancy", 0)
            for floor in self.floors.values()
            for room in floor.get("rooms", [])
        )

        corridor_people = int(total_people * corridor_spawn_ratio)
        corridor_cells = list(self.corridor_cells)

        placed = 0
        attempts = 0

        while placed < corridor_people and attempts < 3000 and corridor_cells:
            fid, x, y = self.random.choice(corridor_cells)

            if not self.passable(fid, (x, y)):
                attempts += 1
                continue

            grid = self.grids[fid]

            if grid.is_cell_empty((x, y)) and not any(
                isinstance(a, SmokeAgent) for a in grid.get_cell_list_contents((x, y))
            ):
                e = EvacueeAgent(self.next_id(), self)
                e.floor = fid
                grid.place_agent(e, (x, y))
                self.agents.add(e)
                placed += 1

            attempts += 1

        # pozar
        hazards = layout.get("hazards", {})
        for source in hazards.get("fire_sources", []):
            sfid = source["floor"]
            sx = source["position"]["x"]
            sy = source["position"]["y"]

            first_smoke = SmokeAgent(self.next_id(), self)
            first_smoke.floor = sfid
            self.grids[sfid].place_agent(first_smoke, (sx, sy))
            self.agents.add(first_smoke)

            # prikazi pozar u polaznoj celiji kak je u JSONu definirano
            self.walls.discard((sfid, sx, sy))

        self.random_cfg = hazards.get("random_fire_sources", {})
        self.random_fire_triggered = False
        self.random_fire_delay = self.random_cfg.get("delay", 15)

        if self.random_cfg.get("enabled", False):
            count = self.random_cfg.get("count", 1)

            for _ in range(count):
                fid = self.random.choice(
                    self.random_cfg.get("allowed_floors", list(self.floors.keys()))
                )
                grid = self.grids[fid]

                while True:
                    x = self.random.randrange(grid.width)
                    y = self.random.randrange(grid.height)
                    if self.passable(fid, (x, y)):
                        break

                smoke = SmokeAgent(self.next_id(), self)
                smoke.floor = fid

                grid.place_agent(smoke, (x,y))
                self.agents.add(smoke)

        self.reset_agent_knowledge()
        print("Model inicijaliziran")
        ground_exits = 0
        upper_exits = 0

        for f, _, _ in self.exits:
            if f == 0:
                ground_exits += 1
            else:
                upper_exits += 1

        print(f"Izlaz prizemlje : {ground_exits}")
        print(f"Izlaz 1. kat: {upper_exits}")

    def reset_agent_knowledge(self):
        for a in self.agents:
            if isinstance(a, EvacueeAgent):
                a.blocked_cells.clear()
                a.visible_cells.clear()
                a.alarm_heard = False

    # ovo svaki agent ima svoj ID
    def next_id(self):
        self.id_counter += 1
        return self.id_counter

    # provjeri jel agent unutar grida da ne bi hodao van njega
    def in_bounds(self, floor_id, pos):
        x, y = pos
        grid = self.grids[floor_id]
        return 0 <= x < grid.width and 0 <= y < grid.height

    # prolaznost
    def passable(self, floor_id, pos, agent = None):
        x, y = pos

        if not self.in_bounds(floor_id, pos):
            return False

        if (floor_id, x, y) in self.walls:
            return False

        if self.has_smoke(floor_id, pos):
            return False

        if agent is not None and hasattr(agent, "blocked_cells"):
            if (floor_id, x, y) in agent.blocked_cells:
                return False

        cell_contents = self.grids[floor_id].get_cell_list_contents(pos)
        for a in cell_contents:
            # ako je zid ili požar blokiraj prolaznost
            if isinstance(a, WallAgent):
                return False

        evacuees = sum(isinstance(a, EvacueeAgent) for a in cell_contents)
        if evacuees >= 3:
            #print(f"puna celija {floor_id, pos}: {evacuees} ljudi")
            return False

        return True

    def has_smoke(self, floor_id, pos):
        cell = self.grids[floor_id].get_cell_list_contents(pos)
        return any(isinstance(a, SmokeAgent) for a in cell)

    # gleda 4 susjedna polja
    def neighbors4(self, floor_id, pos, agent=None):
        x, y = pos
        cand = [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
        passable_cand = [p for p in cand if self.passable(floor_id, p, agent)]

        return sorted(
            passable_cand,
            key=lambda p: (floor_id, p[0], p[1]) not in self.corridor_cells
        )


    def reset_exit_step_capacity(self):
        for k in self.exit_flow_step:
            self.exit_flow_step[k] = 0

    def request_exit_pass(self, exit_key):
        info = self.exit_info.get(exit_key)

        if info is None:
            return True

        capacity = info["capacity"]

        if self.exit_flow_step[exit_key] >= capacity:
            return False

        self.exit_flow_step[exit_key] += 1
        self.exit_flow_total[exit_key] += 1
        #print(f"Izlaz {exit_key}: {self.exit_flow_step[exit_key]}/{capacity} korišteno")
        return True

    # širenje požara
    def spread_smoke(self):
        smoke_agents = [a for a in self.agents if isinstance(a, SmokeAgent)]

        MAX_HEAT = 25.0  # max toplina

        for s in smoke_agents:
            fid = s.floor
            x, y = s.pos

            # centar požara
            self.heat[fid][(x, y)] = min(MAX_HEAT, self.heat[fid][(x, y)] + 2.0)

            for nx, ny in self.neighbors4(fid, (x, y)):
                self.heat[fid][(nx, ny)] = min(MAX_HEAT, self.heat[fid][(nx, ny)] + 0.5)

        for s in list(smoke_agents):
            fid = s.floor
            x, y = s.pos
            key = (fid, x, y)
            if key in self.ventilation_cells:
                self.grids[s.floor].remove_agent(s)
                self.agents.remove(s)
                self.heat[fid][(x, y)] = 0.0

        smoke_agents = [a for a in self.agents if isinstance(a, SmokeAgent)]

        self.random.shuffle(smoke_agents)

        for s in smoke_agents:
            sfid = s.floor
            pos = s.pos

            neighbors = self.grids[sfid].get_neighborhood(
                pos,
                moore=self.smoke_spread_moore,
                include_center=False
            )

            for nb in neighbors:
                if self.passable(sfid, nb) and not any(
                    isinstance(a, SmokeAgent)
                    for a in self.grids[sfid].get_cell_list_contents(nb)
                ):
                    cell_heat = self.heat[sfid][pos]
                    spread_prob = self.smoke_spread_prob + min(0.3, cell_heat * 0.02)

                    if (sfid, nb[0], nb[1]) in self.ventilation_cells:
                        spread_prob *= 0.15

                    if self.random.random() < spread_prob:
                        new_smoke = SmokeAgent(self.next_id(), self)
                        new_smoke.floor = sfid
                        self.grids[sfid].place_agent(new_smoke, nb)
                        self.agents.add(new_smoke)

        for fid in self.heat:
            for pos in self.heat[fid]:
                self.heat[fid][pos] = max(0.0, self.heat[fid][pos] - 0.1)


    def get_cost(self, floor, pos, agent=None):
        cell = self.grids[floor].get_cell_list_contents(pos)

        # zid = neprolazno
        if any(isinstance(a, WallAgent) for a in cell):
            return 1000

        # agent zna da je nešto opasno npr dpbio poruku ili vidio dim
        if agent is not None:
            if(floor, pos[0], pos[1]) in agent.blocked_cells:
                return 1000

        if (floor, pos[0], pos[1]) in self.corridor_cells:
            base_cost = 0.6
        else:
            base_cost = 1.0

        # strategije
        if agent is None or agent.strategy == "shortest":
            if self.has_smoke(floor, pos):
                return base_cost + 5
            return base_cost

        if agent.strategy == "safest":
            smoke_penalty = 0

            if self.has_smoke(floor, pos):
                smoke_penalty += 10

            for n in self.neighbors4(floor, pos):
                if self.has_smoke(floor, n):
                    smoke_penalty += 3

            return base_cost + smoke_penalty

        if agent.strategy == "least_crowded":
            density = len([
                a for a in self.grids[floor].get_cell_list_contents(pos)
                if isinstance(a, EvacueeAgent)
            ])
            return base_cost + density * 3

        return base_cost

    # dijkstrin algoritam
    def dijkstra_next_step(self, floor_id, start_pos, agent=None):
        sx, sy = start_pos

        if (floor_id, sx, sy) in self.final_exits:
            return (floor_id, start_pos)

        start_state = (floor_id, sx, sy)

        pq = [(0, start_state)]
        dist = {start_state: 0}
        prev = {start_state: None}
        visited = set()

        while pq:
            curr_dist, current_state = heapq.heappop(pq)
            cfid, cx, cy = current_state

            if current_state in visited:
                continue
            visited.add(current_state)

            if current_state in self.exits:
                step = current_state
                while prev[step] is not None and prev[step] != start_state:
                    step = prev[step]
                return (step[0], (step[1], step[2]))

            for nb in self.neighbors4(cfid, (cx, cy), agent):
                nx, ny = nb
                nb_state = (cfid, nx, ny)
                new_dist = curr_dist + self.get_cost(cfid, (nx, ny), agent)

                if nb_state not in dist or new_dist < dist[nb_state]:
                    dist[nb_state] = new_dist
                    prev[nb_state] = (cfid, cx, cy)
                    heapq.heappush(pq, (new_dist, nb_state))

            if (cfid, cx, cy) in self.exits:
                penalty = 0
                if (cfid, cx, cy) not in self.final_exits:
                    penalty = 15   # emergency izlaz je lošiji

                exit_state = (cfid, cx, cy)
                new_dist = curr_dist + penalty

                if exit_state not in dist or new_dist < dist[exit_state]:
                    dist[exit_state] = new_dist
                    prev[exit_state] = current_state
                    heapq.heappush(pq, (new_dist, exit_state))

            # stepenice
            key = (cfid, cx, cy)
            if key in self.stair_links:
                tfid = self.stair_links[key]

                if self.in_bounds(tfid, (cx, cy)) and (tfid, cx, cy) not in self.walls:
                    nb_state = (tfid, cx, cy)

                    stair_cost = 0.5

                    if self.has_smoke(tfid, (cx, cy)):
                        stair_cost += 4

                    target_heat = self.heat[tfid].get((cx, cy), 0)
                    if target_heat > 5:
                        stair_cost += target_heat * 1.5

                    stair_dist = curr_dist + stair_cost

                    if nb_state not in dist or stair_dist < dist[nb_state]:
                        dist[nb_state] = stair_dist
                        prev[nb_state] = (cfid, cx, cy)
                        heapq.heappush(pq, (stair_dist, nb_state))

        return None

    # manhattan udaljenost do najblizeg izlaza na istom katu
    def distance_to_nearest_exit(self, floor, pos):
        exits_on_floor = [
            (x, y) for (f, x, y) in self.exits if f == floor
        ]

        if not exits_on_floor:
            return None

        x, y = pos
        return min(abs(x - ex) + abs(y - ey) for ex, ey in exits_on_floor)

    # ima ikakav put do izlaza
    def can_escape(self, evacuee):
        fid = getattr(evacuee, "floor", 0)
        res = self.dijkstra_next_step(fid, evacuee.pos, evacuee)
        return res is not None

    #  koraci
    def step(self):
        self.reset_exit_step_capacity()
        if not self.running:
            return

        self.spread_smoke()

        for alarm in self.alarms:
                if not alarm.active:
                    continue

                grid = self.grids[alarm.floor]
                neighbors = grid.get_neighborhood(
                    alarm.position,
                    moore=True,
                    radius=alarm.radius,
                    include_center=True
                )

                for pos in neighbors:
                    for agent in grid.get_cell_list_contents(pos):
                        if isinstance(agent, EvacueeAgent) and not agent.alarm_heard:
                            agent.alarm_heard = True
                            agent.panic = min(1.0, agent.panic + 0.2)
        self.steps += 1
        self.agents.do("step")

        self.dead_count = sum(
            1 for a in self.agents
            if isinstance(a, EvacueeAgent) and getattr(a, "dead", False)
        )

        current_evacuees = [
            a for a in self.agents
            if isinstance(a, EvacueeAgent)
            and not getattr(a, "dead", False)
            and not getattr(a, "evacuated", False)
        ]

        can_anyone_escape = any(self.can_escape(a) for a in current_evacuees)

        for exit_key in self.exit_info:
            self.exit_flow_history[exit_key].append(self.exit_flow_step[exit_key])

            fid, ex, ey = exit_key
            q = 0
            for nb in self.neighbors4(fid, (ex, ey)):
                q += sum(
                    1 for a in self.grids[fid].get_cell_list_contents(nb)
                    if isinstance(a, EvacueeAgent) and not getattr(a, "dead", False) and not getattr(a, "evacuated", False)
                )
            self.exit_queue_history[exit_key].append(q)


        self.history["steps"].append(self.steps)
        self.history["evacuated"].append(self.evacuated_count)
        self.history["dead"].append(self.dead_count)

        if hasattr(self, "step_signal"):
            self.step_signal.value += 1


        if not current_evacuees or not can_anyone_escape:
            total_people = self.evacuated_count + self.dead_count + len(current_evacuees)
            survival_rate = (self.evacuated_count / total_people * 100) if total_people > 0 else 0

            status_msg = "ZAVRŠENO (Svi procesuirani)" if not current_evacuees else "PREKINUTO (Izlazi blokirani)"

            print(f"\n{status_msg}")
            print("--- Izvještaj o evakuaciji ---")
            print(f"Uspješno evakuirani: {self.evacuated_count}")
            print(f"Poginuli u dimu: {self.dead_count}")
            print(f"Zarobljeni unutra: {len(current_evacuees)}")
            print(f"Stopa preživljavanja: {survival_rate:.2f}%")
            print(f"Trajanje simulacije: {self.steps} koraka\n")

            self.running = False
            return

