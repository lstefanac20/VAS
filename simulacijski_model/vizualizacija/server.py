from mesa.visualization import SolaraViz
from mesa.visualization.components import make_space_component
from model.model import EvaluationModel
from .portrayal import building_portrayal
import solara
from types import SimpleNamespace
import matplotlib.pylab as plt

model = EvaluationModel("podaci/building_layout.json")
space = make_space_component(building_portrayal)

step_signal = solara.reactive(0)
model.step_signal = step_signal

@solara.component
def GroundFloorPage(model):
    proxy_model = SimpleNamespace(
        grid=model.grids[0],
        agents=model.agents,
        active_floor = 0,
        heat = model.heat
    )
    solara.Markdown("## Prizemlje")
    space(proxy_model)

@solara.component
def FirstFloorPage(model):
    proxy_model = SimpleNamespace(
        grid=model.grids[1],
        agents=model.agents,
        active_floor = 1,
        heat = model.heat
        )
    solara.Markdown("## 1. kat")
    space(proxy_model)

@solara.component
def ExitFlowPlot(model, last_n: int = 100):
    _ = step_signal.value
    steps = model.steps
    n = min(last_n, steps)

    fig = plt.figure(figsize=(10, 6))
    ax = fig.add_subplot(111)

    exit_data = {}
    max_len = 0

    for exit_key, info in model.exit_info.items():
        hist = model.exit_flow_history.get(exit_key, [])
        if hist:
            exit_data[info["id"]] = hist
            max_len = max(max_len, len(hist))

    if not exit_data:
        solara.FigureMatplotlib(fig)
        return

    start_step = max(0, max_len - n)
    x_steps = list(range(start_step, max_len))

    bottom = [0] * len(x_steps)

    for exit_name, hist in exit_data.items():
        y_data = hist[start_step:max_len]

        ax.bar(x_steps, y_data, label=exit_name, bottom=bottom, width=0.8)

        bottom = [bottom[i] + y_data[i] for i in range(len(y_data))]

    ax.set_title("Protok evakuiranih po izlazima")
    ax.set_xlabel("Korak simulacije")
    ax.set_ylabel("Broj evakuiranih u koraku")
    ax.legend(loc="upper left")
    ax.grid(True, axis='y', alpha=0.3)

    solara.FigureMatplotlib(fig)

@solara.component
def EvacuationProgressPlot(model):
    _ = step_signal.value
    if not model.history["steps"]:
        return

    fig = plt.figure()
    ax = fig.add_subplot(111)

    ax.plot(
        model.history["steps"],
        model.history["evacuated"],
        label = "Evakuirani"
    )
    ax.plot(
        model.history["steps"],
        model.history["dead"],
        label="Poginuli",
    )

    ax.set_title("Tijek evakuacije kroz vrijeme")
    ax.set_xlabel("Broj ljudi")
    ax.set_ylabel("Broj koraka")
    ax.legend()

    solara.FigureMatplotlib(fig)

@solara.component
def MainPage(model):
    solara.Markdown("#Simulacija")

    with solara.Column(gap="20px"):
        with solara.Row(gap="20px"):
            with solara.Column(style={"width": "50%"}):
                GroundFloorPage(model)
            with solara.Column(style={"width": "50%"}):
                FirstFloorPage(model)

        with solara.Row(gap="20px"):
            with solara.Column(style={"width": "50%"}):
                ExitFlowPlot(model)

            with solara.Column(style={"width": "50%"}):
                EvacuationProgressPlot(model)


server = SolaraViz(
    model,
    components = [MainPage],
    name="Simulacija evakuacije zgrade",
    use_threads=False
)
