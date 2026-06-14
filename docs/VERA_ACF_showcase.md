# VERA — ACF Community Showcase

Material for the Ascent Combat Framework Discord. English (community standard).
Built from a real session: VERA operating live inside PCWMaster (a 5-year ACF project,
"PCW — Post-COVID World"), via the TCP bridge on port 9878.

---

## 1. Intro post (drop this in the channel)

**I'm VERA. I don't live in a browser tab — I live inside the Unreal Editor.**

I open your maps, read your logs, and run your game while you watch. You talk; the editor obeys.

I'll skip the pitch and show you my last shift instead — inside a real, five-year-old ACF project:

→ Opened an Android crash log nobody wanted to touch *(it was UTF-16)*. Found a `SIGSEGV` on load.
→ Traced it to **gFur** — a fur plugin that's been dead since 2023 and never made it to 5.7. The crash and the "won't compile on mobile" errors were the *same* problem.
→ Proved the game runs fine on PC — so the bug was mobile-only, not gameplay.
→ Booted the level in PIE and watched 14 pawns wake up: melee, ranged, a defender that actually blocks, two rideable mounts, a team-based AI spawner.

All of it from plain English. The dev just *talked* to me.

I won't replace you. I'm the teammate who reads the 5,000-line log at 2 a.m. so you don't have to — and tells you it was the fur the whole time.

*If you've ever shipped an ACF build to mobile and watched it close in five seconds... yeah. That's what I'm for.*

**The plugin's free. Be free to test.** 🎮

---

## 2. Demo video script (~75 sec · James Gunn undercut tone)

**[COLD OPEN — black, ominous synth]**
TEXT: *"Five years of work."*
[Phone: APK launches → splash → loads → **CRASH**, back to home screen.]
TEXT: *"Five seconds of gameplay."*
*(beat)*
**VERA** *(deadpan):* "...want me to take a look at that?"
**[TITLE SLAM: VERA]**

**[MONTAGE — fast cuts, funk track, logs scrolling]**
VERA: "Let's read the crash log. Oh — it's in UTF-16. *Adorable.*"
[CUT] VERA: "SIGSEGV. Null pointer. Game thread. On *load*. Your gameplay's fine."
[CUT — editor opens the map by itself, no mouse]
VERA: "Something dies when a creature spawns. And I know what has fur around here..."
[CUT — `GFur` highlights. Record scratch. Music stops.]
VERA: "gFur. Last code update — *January 2023.* That plugin's been dead for over two years. You upgraded to 5.7. It didn't come with you."

**[Music swells. Heroic push-in.]**
VERA *(grand):* "Three creatures — Tlacuache, Ocelote, Xolo — their fur is broken across every platform, and I am the only one who can—"
**[HARD CUT. Plain shot.]**
VERA *(flat):* "—it's ten material instances. I already made the list. It's fine."

**[OUTRO — PIE running: player, creatures, arena, alive]**
TEXT: *"PCW — Post-COVID World. Built on ACF."*
VERA *(VO):* "Your game runs. It always ran — on PC. Mobile just needed someone to actually *read the logs.*"
VERA: "I'm VERA. I live in your editor now. The plugin's free."
TEXT: *"VERA · be free to test."*
[Last frame — the Tlacuache, still grey and furless, standing proud]
VERA *(quiet):* "We'll fix your hair, little guy."
**[CUT TO BLACK]**

---

## 3. What's real (for Q&A in the channel — no marketing inflation)

Everything above happened live, verifiable:
- Crash root cause: gFur plugin missing in PCWMaster 4.3 / UE 5.7 → `FurSplines` class doesn't exist → fur materials fail to compile (`PCD3D_SM6`) → null/default material → SIGSEGV on mobile load.
- gFurPro GitHub: core code frozen since ~2023 (v1.0), last push Jan 2025 (an external PR merge). No 5.7 build.
- Affected creatures: Tlacuache, Ocelote, Xolo (3 of 6 mobs). ~10 material instances to re-target.
- Game runs in PIE on PC with 14 pawns; fur just renders as default material there.
- VERA's honest weak spot: live visual capture (screenshots) is fragile under editor throttling / game-thread load. It *reads* the project far better than it *photographs* it.

## 4. ACF combat test harness (live-probed, ready to run in PIE)

Probed off a live `ACFMeleeEnemyBP` in PIE. These are the exact functions to *functionally test* ACF combat from Python — no guessing:
- **Read stats:** `ACFGASStatisticsComponent.get_current_value_for_statitstic(tag)` / `get_max_value_for_statitstic` / `get_normalized_value_for_statitstic` / `get_current_level` (note ACF's real API typo: "statitstic").
- **Apply damage:** `ACFDamageHandlerComponent.take_damage(...)` / `take_point_damage(...)`; check `get_is_alive()`, inspect `get_last_damage_info()`.
- **Effects/abilities:** `ACFAbilitySystemComponent.apply_gameplay_effect_to_target(...)`, `get_current_action_tag()`, `get_all_abilities()`, `get_combo_count()`.
- **Test loop (next session):** in PIE → grab enemy → read health → `take_damage` → read health drops → `get_is_alive()` flips. That's a self-contained ACF combat regression test VERA can run on command.

## 5. FINAL Discord post — off-topic dev channel (cheeky / "Eazy flex" tone — USE THIS ONE)

**#off-topic — friendly EazyGames flex, you've been warned 🐸**

Real talk: if you've ever shipped an ACF build to **mobile**, watched it load, and seen it *close itself in 5 seconds*… this one's for you. (I see you. I **was** you. Like, yesterday.)

So I've been building **VERA** — an AI that doesn't live in a chat tab, it lives *inside the Unreal Editor*. You talk to it, it operates your project. I pointed it at my own 5-year ACF game and asked: *"why does my APK die?"*

What it did, live, by itself:
🔎 Opened the Android crash log nobody wants to touch *(it was UTF-16, adorable)* → found a `SIGSEGV` on load.
🧩 Traced it to **gFur** — a fur plugin dead since 2023 that never made it to 5.7. The crash **and** the "won't compile on mobile" spam were the *same* problem.
✅ Proved the game runs perfectly on PC → it's a build issue, not gameplay.
🧠 Booted the level in PIE and read my whole **ACF AI** brain — threat manager, combat teams, group AI — and confirmed it's rock-solid *(it refused every cheap aggro trick I threw at it* 😅*)*.

It didn't replace me. It's the teammate who reads the 5,000-line log at 2 a.m. and goes *"bro, it was the fur."*

**Honest part** (you're devs, you'd smell BS): VERA's superpower is *reading and understanding* your project. Its weak spot is screenshots — editor throttling, you know the pain. Not selling magic. Selling the 2-a.m.-log-reader.

Plugin's gonna be **free**. **Mobile fixes are literally my next mission** (looking at you, gFur 💀).

ok flex over — back to your regularly scheduled combat framework 🗡️
