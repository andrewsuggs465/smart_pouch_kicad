# SecurePouch — Technical Product Specification
**Status:** In Development — Pre-Prototype  
**Last Updated:** June 2026 — rev. siren (CEB-35FD29 + H-bridge); rev. backend (FMD fork, Oracle Cloud); rev. biometric (SEN0348 capacitive); rev. materials confirmed; rev. closure (solenoid pin latch confirmed, acoustic cavity in Brick B); rev. scope (RFID + IPX4 + RF compliance removed; 5-unit JLCPCB prototype run)  
**Document Purpose:** Reference specification for hardware, software, and physical design decisions made to date.

---

## 1. Product Overview

A smart anti-theft travel security pouch combining slash-resistant physical construction with integrated LTE-M/GNSS tracking, BLE proximity detection, biometric access control, and an active alarm system. Targeted at safety-conscious travelers, international tourists, urban daily commuters, and concerned parents.

**Business model:** One-time device purchase + cellular data subscription (via Hologram eUICC).

---

## 2. Design Requirements

| Requirement | Notes |
|---|---|
| Portable & lightweight | Target total weight <150g including electronics |
| Slash / stab resistant | Primary physical security requirement |
| Easy to use | Single-tap arm/disarm; biometric or remote unlock |
| Global connectivity | LTE-M/NB-IoT on Hologram's 550+ carrier network |
| End-to-end encryption | All device–server and server–client communication |
| Accessible without phone | Web dashboard functional from any browser |
| Fail-safe locking | Mechanical key override if electronics fail |

**Acknowledged trade-offs:** Security vs portability; subscription cost vs cellular capability; RF regulatory compliance (FCC/CE) required before commercialisation.

---

## 3. Physical Design

### 3.1 Materials

| Item | Part No. | Supplier | Description | Role |
|---|---|---|---|---|
| Outer shell | 40201.ANTHR | Extremtextil | 500D Cordura, PU-coated nylon, 1.5 m width | Primary outer fabric; abrasion resistant |
| Cut/stab layer | 21-131 | TEXfire | Aramid PARATEX 400P, 150 cm width | Para-aramid inner layer; slash and stab resistance |
| Inner lining | 73078.SW | Extremtextil | Diamond Ripstop-Nylon, Robic Ocean Recycling, 70 den, UTS-coated, 100 g/m², 1.49 m width | Interior lining; lightweight tear-resistant backing |
| Sewing thread | 71980.ROHGLB | Extremtextil | Kevlar/Aramid thread, Size 75, 100 m | Structural stitching through cut-resistant layers |

**Tooling:** Kretzer Finny TecX1 micro-serrated scissors, 8 cm (Extremtextil 70954) — required for clean cuts through aramid fabric.

**Material stack (cross-section, outside to inside):**
```
[500D Cordura PU nylon]     ← abrasion, aesthetics
[Aramid PARATEX 400P]       ← slash and stab resistance
[Robic Diamond Ripstop]     ← interior finish, lightweight
```

**Note:** The previous spec called for UHMWPE (Dyneema) as the slash layer. The chosen PARATEX 400P is a para-aramid (comparable to Kevlar 400 gsm) providing equivalent or better stab resistance with good slash resistance, and is more readily available from TEXfire in cut-to-size form.

### 3.2 Dimensions (Compact Variant)
- **Length:** ~155 mm (passport standard + margin)
- **Width:** ~98 mm
- **Depth:** TBD — pending lock/brick assembly design
- **Wearing:** Neck/shoulder lanyard, cross-body strap, or jacket pocket

### 3.3 Closure & Lock — Two-Brick Solenoid Pin Design

The zipper-based closure has been abandoned. The design uses **two rigid metal (aluminium) brick enclosures** latched together by a spring-loaded solenoid pin, with the fabric passport body suspended between them.

```
[BRICK A]  ══════ fabric body ══════  [BRICK B]
PCB + electronics                     Latch pin receiver hole
LiPo battery                          Acoustic cavity (piezo siren)
Solenoid (pin actuator) ──pin──►      ◄── pin seats here when locked
USB-C port                            Fingerprint sensor (flush-mounted)
BLE trace antenna
```

**Latch mechanism — solenoid pin (confirmed):**
- Spring-loaded steel pin in Brick A extends into a machined receiver hole in Brick B
- Spring holds pin extended = **fail-locked by default**; solenoid retracts pin briefly to unlock
- Single GPIO + 2N7002 MOSFET drives solenoid; brief current pulse only on unlock event (~0.5 s)
- Solenoid supply: battery rail (3.7 V) or small 5 V boost — test empirically for adequate retraction force
- Rigid machined brick faces guarantee pin alignment — the main weakness of solenoid pins in flexible designs does not apply here

**Rationale over servo cam:** Servo cam tolerates misalignment via camming action, which is unnecessary in a rigid metal enclosure. Solenoid pin is simpler (one moving part), smaller, lighter, inherently fail-locked, and requires no PWM — just a GPIO pulse.

**Mechanical fallback — recessed key slot:**
- Keyhole on Brick A face manually drives a push rod that retracts the solenoid pin
- Operates without any power
- Key slot recessed into brick body; not accessible without the correct key

**Acoustic cavity — Brick B outer face:**

The CEB-35FD29 piezo disc (35 mm diameter) is housed in Brick B to keep its wires and mass off the electronics brick:
```
Brick B outer wall (cross-section):
┌─────────────────────────────┐
│  6 mm aperture hole ──►  ))) sound out
│  ┌───────────────────┐      │
│  │  ~8 mm deep dome  │      │  ← Helmholtz cavity (~5–8 cm³)
│  │  cavity           │      │
│  └───────────────────┘      │
│  CEB-35FD29 disc bonded     │  ← epoxy at disc rim
│  to rim (35 mm Ø)           │
│  Wire leads → channel       │  ← routed to Brick A PCB
└─────────────────────────────┘
```
- Cavity depth ~8 mm; aperture ~6 mm diameter; tuned nominally for 2.9 kHz
- Adds ~10 mm to Brick B depth (acceptable — Brick B is thinner than Brick A anyway)
- Disc bonded with epoxy at rim; wire leads routed through internal channel to Brick A

**Discretion concern (open):** Whether the two-brick form factor reads as discrete travel gear or conspicuous hardware is unresolved — evaluate with physical mock-up.

### 3.4 Electronics Housing — Brick A
- Contains: PCB, LiPo battery, solenoid, USB-C charging port
- BLE PCB trace antenna faces outward (no metal obstruction on that face)
- PCB module designed to be serviceable without fabric disassembly
- Brick B contains: latch receiver, acoustic cavity, fingerprint sensor (flush-mounted on outer face)

---

## 4. Electronic Architecture

### 4.1 Block Diagram Summary

```
[LiPo Battery]
      │
  [nPM1300 PMIC]
  ┌───┴────────────────────────────────┐
  │  BUCK1 (1.8V) ──► nRF52840        │
  │  Battery rail ──► nRF9151          │
  │  Battery rail ──► MT3608 boost     │
  │  USB-C PD input                    │
  └────────────────────────────────────┘
         │
     [MT3608]
     15V boost
         │
    [H-Bridge]  ◄── 2× GPIO (nRF52840)
         │
   [CEB-35FD29]  (piezo disc, wire leads)

[nRF9151] ◄──UART──► [nRF52840]
    │                     │
  LTE-M               BLE 5.3
  NB-IoT              Accelerometer (I2C)
  GNSS                Fingerprint (UART)
  App logic           Servo cam lock (PWM) → replaced by solenoid (GPIO)
                      Solenoid pin lock (GPIO + MOSFET)
                      H-bridge siren (2× GPIO @ 2.9 kHz)
                      Feedback wire (ADC, optional resonance lock)
                      Strobe LED (GPIO/PWM)
                      Status LEDs
```

### 4.2 Core ICs

| Component | Part | Function |
|---|---|---|
| Application MCU + LTE-M/GNSS | Nordic nRF9151-SICA | Cortex-M33 @ 64 MHz; LTE-M/NB-IoT modem; integrated GNSS; PSM ~2.5 μA sleep |
| BLE SoC + peripheral MCU | Nordic nRF52840 | Cortex-M4F @ 64 MHz; BLE 5.3; 256 KB RAM; 1 MB flash; drives all local peripherals |
| PMIC | Nordic nPM1300-CAAA-R | USB-C PD charging (up to 1.5 A); fuel gauge; BUCK1 (1.8 V→nRF52840); battery rail (3.7 V→nRF9151) |
| Accelerometer | Bosch BMA400 | Triaxial; I2C; <1 μA wake mode; hardware motion-wakeup interrupt; 2×2 mm |
| Boost converter (siren) | MT3608 (C84446) | Battery → 15 V for H-bridge siren drive (30 V p-p across piezo disc) |

**Inter-MCU communication:** UART (bidirectional). nRF9151 acts as primary application processor and LTE-M/GNSS hub; nRF52840 handles BLE proximity, local sensor polling, and actuator control.

---

## 5. Connectivity

### 5.1 Cellular
- **Technology:** LTE-M primary, NB-IoT fallback
- **Modem:** Integrated in nRF9151
- **SIM:** Hologram Hyper eUICC — nano (4FF) form factor; 190+ countries; 550+ carrier networks; OTA profile management
- **Power saving:** PSM (Power Saving Mode) + eDRX; modem target: minutes-long sleep between location pings

### 5.2 GNSS
- **Receiver:** Integrated in nRF9151
- **Constellations:** GPS, GLONASS, Galileo, BeiDou
- **Assisted GNSS:** A-GNSS via nRF Cloud for <5 s cold start
- **Fallback:** Cell-ID and Wi-Fi positioning via nRF Cloud Location Services

### 5.3 BLE
- **Radio:** nRF52840 (BLE 5.3)
- **Primary use:** Dead-man switch — alarm triggers when BLE connection to user's phone is lost beyond configurable proximity threshold
- **Antenna:** PCB trace inverted-F; no separate component

### 5.4 Antennas
| Antenna | Part | Notes |
|---|---|---|
| Cellular + GNSS (2-in-1) | Taoglas FXP301 | 600 MHz–8 GHz cellular + GNSS L1; 105×20×0.24 mm flex PCB; peel-and-stick; dual IPEX |
| BLE | PCB trace (inverted-F) | 2.4 GHz; no component; requires keep-out zone in PCB layout |

---

## 6. Locking System

### 6.1 Primary Lock — Servo Cam (Electromechanical)
- Small servo motor rotates a cam that blocks the zipper pull
- Holds locked position without continuous current draw
- Fail-locked on power loss
- Controlled via PWM from nRF52840

### 6.2 Backup — Mechanical Key Override
- Spring-loaded deadbolt on pouch side edge
- User can unlock manually regardless of battery or electronics state
- Required for regulatory safety and consumer confidence

### 6.3 Unlock Methods (in priority order)
1. Fingerprint sensor (biometric)
2. Remote unlock via LTE-M (web dashboard or app)
3. BLE unlock command from paired phone
4. Physical key (mechanical override)

### 6.4 Auto-Lock (Dead-Man Switch)
- Triggers when BLE RSSI drops below threshold (phone out of range)
- Configurable delay before alarm (default: 30 s) to reduce false positives
- Alarm fires simultaneously with lock engagement

---

## 7. Alarm System

### 7.1 Siren — Same Sky CEB-35FD29

| Parameter | Value |
|---|---|
| Part | Same Sky CEB-35FD29 |
| Type | Piezoelectric disc element with feedback electrode |
| Diameter | 35 mm |
| Thickness | 0.63 mm |
| Weight | 3.5 g |
| Resonant frequency | 2.9 kHz (range 2.4–3.4 kHz) |
| Max drive voltage | 30 V peak-to-peak |
| Impedance | 500 Ω |
| Termination | Wire leads — red (drive +), black (drive −/GND), blue (feedback) |
| Mounting | Mechanical (not PCB-mounted); adhered to acoustic cavity or housing; wires route to PCB |

### 7.2 Siren Drive Circuit — Boost + Full H-Bridge

To reach the 30 V p-p maximum rated drive, the circuit uses a boost converter feeding a full H-bridge:

```
Battery (3.7V) → MT3608 boost → 15V rail
                                    │
                              [Full H-Bridge]
                              High-side: 2× BSS84 (P-ch, SOT-23)
                              Low-side:  2× 2N7002 (N-ch, SOT-23, already on BOM)
                                    │
                              CEB-35FD29 disc
                              +15V ──► RED wire
                              −15V ──► BLACK wire  (inverted half-cycle)
                              = 30V p-p across element
```

- **Drive frequency:** nRF52840 generates 2.9 kHz square wave on 2 GPIO pins in opposite phase
- **Feedback wire (blue):** Connected to nRF52840 ADC via voltage divider; firmware can sweep frequency to lock onto resonance peak for maximum SPL
- **Gate resistors:** 100 Ω on each MOSFET gate (already on BOM)
- **New BOM additions:** 2× BSS84 P-channel MOSFET, SOT-23, 30 V; body diodes provide freewheeling for inductive kick protection

**Why H-bridge + boost:** Single-ended drive at 15 V = 15 V p-p. Full H-bridge at 15 V = ±15 V = 30 V p-p — exactly at the rated maximum. This roughly doubles acoustic output vs single-ended drive from the same supply.

**Acoustic housing note:** SPL of a bare piezo disc in open air is modest. Mounting the disc against a sealed cavity with tuned aperture (Helmholtz resonator) or inside a plastic horn significantly increases effective SPL. Acoustic housing design is TBD in mechanical design phase.

### 7.3 Strobe LED

| Parameter | Value |
|---|---|
| Part | Cree XP-E White (XPEWHT-L1-R250-00FE1) |
| Colour temp | 6500 K, 70-CRI |
| Power | 1 W SMT |
| Drive | Battery rail via 2N7002 MOSFET; 8–10 Hz PWM strobe |
| Current limiting | 2.2 Ω series resistor |

### 7.4 Alarm Trigger Conditions
- BLE dead-man switch (phone out of range, configurable delay)
- Accelerometer detects tamper motion pattern (rapid jerk / cutting vibration)
- Remote trigger via LTE-M from web dashboard
- Manual trigger via physical button (TBD placement)

---

## 8. Biometric Access

| Parameter | Value |
|---|---|
| Part | DFRobot SEN0348 |
| Mouser | 426-SEN0348 |
| Type | Capacitive |
| Interface | UART → nRF52840 |
| Template storage | 80 fingerprints (on-module; no MCU RAM required) |
| Resolution | 508 dpi |
| Supply voltage | 3.3 V (BUCK1 rail) |
| Active current | 60 mA |
| Dimensions | 21 × 5 mm |
| Operating temp | −40 °C to +60 °C |
| FAR | <0.001% |

Capacitive sensing provides reliable reads on wet, dirty, or dry fingers — directly addressing the key failure mode of optical sensors in travel use cases. The ultra-thin 5 mm profile is well-suited for flush-mounting into the pouch surface. 80 templates is sufficient for personal use (typically 3–5 fingers stored across 1–2 users).

**Note:** Physical key override remains the fallback for all biometric failure scenarios.

---

## 9. Power Architecture

| Rail | Source | Consumers |
|---|---|---|
| 3.7–4.2 V (battery) | LiPo → nPM1300 pass-through | nRF9151 VDD; MT3608 input |
| 1.8 V regulated | nPM1300 BUCK1 | nRF52840 VDD; BMA400; I2C pull-ups |
| 15 V boost | MT3608 (C84446) | H-bridge siren supply only; produces 30 V p-p across CEB-35FD29 disc |
| USB-C input | nPM1300 charger | LiPo charging up to 1.5 A (PD); powers system when plugged in |

**Battery:** LiPo 3.7 V nominal, 800–1000 mAh, flat pouch form, with integrated PCM. JST-PH 2.0 mm connector. Target: multi-day battery life at low LTE-M ping frequency using PSM/eDRX.

**Note:** nPM1300 charging is optimised for up to 1000 mAh. Larger cells can be charged at reduced C-rate.

---

## 10. PCB & Crystals

| Component | Spec |
|---|---|
| 32 MHz crystal | nRF52840 radio clock; ±10 ppm; load cap per nRF52840 datasheet |
| 32.768 kHz crystal (×2) | One per MCU; RTC and PSM timing; ±20 ppm |
| BUCK inductors (×2) | 1.5 μH, ≥300 mA, low DCR, 0402/0603 for nPM1300 BUCK1 and BUCK2 |
| NTC thermistor | 10 kΩ, B3380K; battery temperature sensing for nPM1300 charger |
| USB ESD protection | PRTR5V0U2X, SOT-363 |
| MOSFETs (N-ch) | 2× 2N7002 SOT-23 — H-bridge low-side (siren) + strobe LED drive |
| MOSFETs (P-ch) | 2× BSS84 SOT-23, 30 V — H-bridge high-side (siren only) |

**I2C bus voltage:** 1.8 V rail. Pull-up resistors (4.7 kΩ) to BUCK1 output. Shared bus: BMA400 + nPM1300.

---

## 11. Software & Backend

### 11.1 Server Platform — FMD Server (Forked)

**Base project:** FMD (FindMyDevice) FOSS — `gitlab.com/fmd-foss/fmd-server`  
**Our repo:** Fork of FMD Server (link TBD)  
**Language:** Go  
**Database:** ObjectBox (embedded, no separate DB process)  
**License base:** AGPL-3.0 — fork must remain open source

FMD Server was chosen as the backend because it provides a working web dashboard with map-based location display, command dispatch infrastructure, and an established REST API — all self-hostable. The upstream project is designed for Android phone tracking; our fork adapts it for an IoT embedded device.

**Required fork changes:**
- Implement FMD Server's REST API on nRF9151 firmware (HTTP POST location updates over LTE-M instead of Android app)
- Add new server-side command types: `lock`, `unlock`, `arm`, `disarm`, `alarm` — these do not exist upstream
- Adapt device registration flow for hardware device ID + API key auth (no Android account required)
- Extend web dashboard UI with lock/unlock and alarm controls
- Remove or stub Android-specific features (camera capture, factory reset, etc.)

**Deployment stack:**
```
nRF9151 (LTE-M) ──HTTPS──► FMD Server (Go binary, port 8080)
                              │
                         Caddy reverse proxy (auto TLS, Let's Encrypt)
                              │
                         Browser dashboard (HTTPS required by WebCrypto API)
```

### 11.2 Web Dashboard Features (Target)

- Real-time GNSS location on map (inherited from FMD Server frontend)
- Remote arm/disarm, lock/unlock, alarm trigger controls (custom additions)
- Alert and tamper event log
- Device registration via unique hardware ID + password + email
- Accessible from any desktop or mobile browser without app install
- HTTPS mandatory (WebCrypto API requirement enforced by FMD Server)
- End-to-end encryption for location data (FMD Server encrypts location on-device before upload; retained in fork)

### 11.3 Prototype Hosting — Oracle Cloud Always Free

Since the team is on a university network (eduroam) without the ability to self-host, the prototype server runs on Oracle Cloud's Always Free tier.

| Property | Value |
|---|---|
| Provider | Oracle Cloud Infrastructure (OCI) |
| Tier | Always Free — no time limit, no charges within limits |
| Instance | ARM Ampere A1: up to 4 OCPUs + 24 GB RAM (shared across instances) |
| Fallback | 2× AMD x86 micro (1 OCPU, 1 GB RAM each) — always available if ARM capacity is full |
| OS | Ubuntu 22.04 LTS |
| Services | Docker + Docker Compose; Caddy (auto-TLS); FMD Server container |
| Domain | DuckDNS free subdomain → OCI public IP |
| Cost | £0 / €0 |

**Setup summary:** Docker Compose brings up FMD Server on port 8080 and Caddy as a reverse proxy on 443. Caddy automatically provisions a Let's Encrypt certificate for the DuckDNS subdomain. FMD Server requires HTTPS for the web interface; Caddy handles this with no manual cert management.

**Backup option:** Fly.io — Docker-native PaaS, free allowance, auto-HTTPS with `.fly.dev` subdomain, no DNS config required. Suitable if Oracle account creation is rejected.

---

## 12. Manufacturing

**Prototype run:** 5 fully assembled PCBs ordered from JLCPCB (PCB fabrication + SMT assembly in one order). Consigned parts (nRF9151, nRF52840, nPM1300, Cree LED) shipped to JLCPCB warehouse ahead of assembly order.

| Supplier | Role |
|---|---|
| JLCPCB | PCB fabrication + full SMT assembly; 5-unit prototype run |
| Circuitos Impresos 2CI (Barcelona) | Quick-turn bare PCBs for rapid design iteration if needed (from 4 h turnaround) |
| Hologram (hologram.io) | eUICC SIM provisioning and global data plan |
| Mouser | Component sourcing for consigned parts and off-PCB modules |

**Assembly notes:**
- nRF9151 (LGA), nRF52840 (QFN73), nPM1300 (WLCSP or QFN): all require precision reflow; not hand-solderable
- BLE PCB trace antenna requires copper keep-out zone; verify in DFM before ordering
- FXP301 antenna attaches via adhesive + 2× U.FL connectors post-assembly
- SEN0348 fingerprint module connects via header connector; mounted flush on Brick B outer face
- CEB-35FD29 piezo disc mounts in Brick B acoustic cavity; wire leads route to PCB in Brick A
- SG90 servo removed from design — solenoid pin replaces it for latch actuation

---

## 13. Open Items / TBD

| Item | Status |
|---|---|
| Lock mechanism | **Resolved** — solenoid pin; spring-locked, GPIO + MOSFET drive, recessed key fallback |
| Solenoid voltage / part selection | Test 3.7 V battery rail vs small 5 V boost; select solenoid part based on retraction force testing |
| Brick material & manufacture | Aluminium; machined for prototype (5 units) — CNC or local machine shop |
| Brick form factor discretion | Evaluate with physical mock-up before final dimensions locked |
| Brick A / Brick B split | Confirmed: Brick A = PCB/battery/solenoid; Brick B = receiver/acoustic cavity/fingerprint |
| Acoustic cavity tuning | 6 mm aperture, ~8 mm deep dome in Brick B; validate SPL on physical prototype |
| FMD Server fork — repo setup | Fork gitlab.com/fmd-foss/fmd-server; create team repo |
| FMD firmware client | Implement FMD Server REST API on nRF9151 (HTTPS POST location + command polling) |
| FMD custom commands | Add lock/unlock/arm/disarm/alarm endpoints to forked server |
| FMD dashboard UI extensions | Add lock/alarm controls to web frontend |
| Extended size variant | Dimensions and gusset design TBD |
| Fingerprint wet-finger performance | Resolved — SEN0348 is capacitive |
| Physical button placement | Alarm trigger / manual override button location on brick TBD |
| SIM data plan pricing | Hologram subscription tier TBD based on ping frequency |
