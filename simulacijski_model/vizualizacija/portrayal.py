from model.agent import ExitAgent, WallAgent, EvacueeAgent, StairAgent, SmokeAgent, VentilationAgent, AlarmAgent

def building_portrayal(agent):
    if agent is None:
        return {}

    # zid
    if isinstance(agent, WallAgent):
        return {
            "color": "black",
            "marker": "s",
            "layer": 1,
        }

    # izlaz
    if isinstance(agent, ExitAgent):
        return {
            "color": "green",
            "size": 30,
            "marker": "s",
            "layer": 1,
        }
    if isinstance(agent, EvacueeAgent):
        model = agent.model
        floor = agent.floor
        x, y = agent.pos
        panic = agent.panic

        has_path = model.can_escape(agent)

        grid = model.grids[floor]
        has_smoke = any(isinstance(a, SmokeAgent) for a in grid.get_cell_list_contents((x, y)))

        # boja panike
        if panic < 0.4:
            color = "#3D85C6"
        elif panic < 0.7:
            color = "#F1C232"
        else:
            color = "#E06666"

        marker = "o"

        #  zaribljeni u sobi ili dimu
        if not has_path and has_smoke:
            color = "#E69138"
            marker = "X"


        return {
            "color": color,
            "size": 25,
            "marker": marker,
            "layer": 3,
        }

    # stepenice
    if isinstance(agent, StairAgent):
        return{
            "marker": "^",
            "color" : "#400040",
            "layer": 1
        }

    # dim
    if isinstance(agent, SmokeAgent):
        floor = agent.floor
        x, y = agent.pos

        heat = agent.model.heat[floor][(x, y)]

        # boja dima ovisno o toplini
        if heat < 3:
            color = "#d3d3d3"
        elif heat < 6:
            color = "#a9a9a9"
        elif heat < 9:
            color = "#696969"
        else:
            color = "#6f0000"

        return {
            "marker": "s",
            "color": color,
            "size": 30,
            "layer": 1,
        }

    # ventilacija
    if isinstance(agent, VentilationAgent):
        return{
            "marker": "s",
            "color": "#b3b300",
            "layer": 1
        }

    # alarm
    if isinstance(agent, AlarmAgent):
        if agent.state == "idle":
            color = "#ffd966"
        elif agent.state == "detected":
            color = "#f6b26b"
        elif agent.state == "active":
            color = "#cc0000"
        else:
            color = "gray"

        return {
            "color": color,
            "size": 40,
            "marker": "s",
            "layer": 4,
        }


    return {}
