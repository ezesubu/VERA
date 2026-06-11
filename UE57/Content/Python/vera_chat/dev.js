"use strict";
// Harness de desarrollo: inyecta eventos falsos para ver la UI sin Unreal.
// Externo (no inline) para correr bajo el mismo CSP que producción.
function demo() {
  const d = (e, ms) => setTimeout(() => veraChat.dispatch(e), ms);
  d({ type: "status", online: true, version: "UE 5.7" }, 0);
  d({ type: "user", msg: "Build a glass bridge between the east and west columns" }, 200);
  d({ type: "progress", agent: "Manager", msg: "routed to Architect" }, 700);
  d({ type: "progress", agent: "Architect", msg: "plan: material, geometry, verification" }, 1500);
  d({ type: "progress", agent: "Python", msg: "executing step 2 of 3" }, 2400);
  d({
    type: "final", status: "success",
    msg: "Done. Glass bridge spanning `3550 units`, verified visually.\n\n```python\nactor.set_actor_scale3d(unreal.Vector(35.5, 3.0, 0.2))\n```",
  }, 3400);
}
document.getElementById("demo-btn").addEventListener("click", demo);
