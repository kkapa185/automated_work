from catalog_explorer import rules as R


def test_r11_products_by_name_link_and_docroot():
    text = ("Use the Deep Learning Toolbox™ and [x](https://www.mathworks.com/products/optimization.html) "
            "see https://www.mathworks.com/help/robotics/ug/foo.html and MATLAB and Simulink.")
    prods = R.detect_products(text, {})
    assert prods == ["Deep Learning Toolbox", "Optimization Toolbox", "Robotics System Toolbox"]
    assert "MATLAB" not in prods and "Simulink" not in prods


def test_r11_simscape_variants_distinct_and_aliases():
    prods = R.detect_products("Simscape Electrical and Econometric Toolbox, Control Systems Toolbox", {})
    assert prods == ["Control System Toolbox", "Econometrics Toolbox", "Simscape Electrical"]


def test_r11_simulink_test_case_sensitive():
    assert R.detect_products("we simulink test things", {}) == []
    assert R.detect_products("use Simulink Test", {}) == ["Simulink Test"]


def test_r12_platforms():
    assert R.detect_platforms("Just MATLAB scripts", []) == ["MATLAB"]
    assert R.detect_platforms("A Simulink model", []) == ["Simulink"]
    assert R.detect_platforms("see https://mathworks.com/products/matlab.html", []) == ["MATLAB"]  # default
    assert R.detect_platforms("Stateflow charts", ["Stateflow"]) == ["Simulink"]
    assert R.detect_platforms("MATLAB and Simulink", []) == ["MATLAB", "Simulink"]


def test_r10_difficulty_base_levels():
    d = lambda lv, **k: R.classify_difficulty(lv, "", "", k.get("hw", "None"))
    assert d(["Bachelor"]) == "Beginner"
    assert d(["Bachelor", "Master's"]) == "Intermediate"
    assert d(["Master's"]) == "Intermediate"
    assert d(["Bachelor", "Master's", "Doctoral"]) == "Intermediate"
    assert d(["Master's", "Doctoral"]) == "Advanced"
    assert d(["Doctoral"]) == "Advanced"
    assert d([]) == "Intermediate"


def test_r10_difficulty_scope_adjustment():
    assert R.classify_difficulty(["Master's"], "advanced, research-level", "", "None") == "Advanced"
    assert R.classify_difficulty(["Master's"], "", "A beginner friendly start", "None") == "Beginner"
    assert R.classify_difficulty(["Bachelor"], "", "", "Required") == "Intermediate"
    assert R.classify_difficulty(["Doctoral"], "", "", "None") == "Advanced"  # capped


def test_r13_project_type_and_area_rules():
    types = R.classify_project_types("Reinforcement learning controller", "Train a neural network controller", [],
                                     "", "", ["Deep Learning Toolbox"])
    assert "AI / Machine Learning" in types and "Control Design" in types
    assert set(types) <= set(R.PROJECT_TYPES)
    areas = R.classify_application_areas("Wind turbine", "Predict faults", ["Sustainability"], "", "", [],
                                         ["Sustainability and Renewable Energy"])
    assert "Energy / Sustainability" in areas
    assert R.classify_application_areas("x", "y", [], "", "", [], ["Drones"]) == ["Aerospace"]


def test_r13_fallbacks_nonempty():
    assert R.classify_project_types("", "", [], "", "", []) == ["System Design"]
    assert R.classify_application_areas("", "", [], "", "", [], []) == ["Education / Research"]


def test_r14_hardware_tags_word_boundaries():
    assert R.detect_hardware_tags("Satellite navigation and intellectual property") == []
    assert R.detect_hardware_tags("Deploy to a Raspberry Pi and Arduino.") == ["Arduino", "Raspberry Pi"]
    assert R.detect_hardware_tags("We simulate an IMU model.") == []  # sensor needs hardware cue
    assert R.detect_hardware_tags("Connect a real IMU to the board.") == ["IMU"]


def test_r14_hardware_required_levels():
    assert R.classify_hardware_required({"required hardware": "This project must be implemented on Microchip hardware."}, "", []) == "Required"
    assert R.classify_hardware_required({}, "You must be implemented on a board", []) in ("Required", "Optional")
    assert R.classify_hardware_required({}, "The design requires a robot kit.", []) == "Required"
    assert R.classify_hardware_required({}, "pure simulation", []) == "None"
    assert R.classify_hardware_required({}, "pure simulation", ["Arduino"]) == "Optional"
    assert R.classify_hardware_required({}, "hardware-in-the-loop testing", []) == "Optional"
    assert R.classify_hardware_required({"required hardware": ""}, "", []) == "None"


def test_r15_partners_normalisation_and_dedupe():
    html = ('**_Industry Partner_:**<br><a href="https://www.microchip.com/en-us/x" target="_blank">'
            '<img src="a.png"></a>\n\n## Next')
    assert R.detect_partners(html, ["Microchip Technology Inc."]) == ["Microchip Technology"]
    assert R.detect_partners("", ["Analog Devices, Inc. (ADI)"]) == ["Analog Devices"]
    assert R.detect_partners("nothing", []) == []
    assert R.detect_partners(html.replace("microchip.com", "unknownco.com"), []) == ["Unknownco"]
    assert R.partner_from_domain("https://www.iogp.org/") == "IOGP"
