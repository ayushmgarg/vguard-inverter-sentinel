;;; ============================================================================
;;; V-Guard Sentinel AI Core - Parametric enclosure + PCB (AutoLISP)
;;; Big Idea Tech 2026 - Team Codey Tingle
;;;
;;; USAGE:  Open AutoCAD -> APPLOAD this file -> type  SENTINEL  <Enter>.
;;;         Draws (a) a 3D solid enclosure with cavity + mounting holes, and
;;;         (b) a 2D dimensioned plan (top view) with PCB + component footprints.
;;; UNITS:  millimetres. Edit the parameters block below to re-size everything.
;;; Tested logic; entity handles are tracked so boolean ops are deterministic.
;;; ============================================================================

(defun c:SENTINEL ( / L W H WALL LID PCBL PCBW PCBX PCBY HOLED HINS
                      encl cav cyl p oy p1 p2 mklay comp )

  ;; ---------------------- PARAMETERS (edit here) ----------------------
  (setq L     95.0   ; enclosure length  (X)
        W     70.0   ; enclosure width   (Y)
        H     35.0   ; enclosure height  (Z)
        WALL   2.5   ; wall thickness
        LID    2.0   ; base/lid thickness
        PCBL  80.0   ; PCB length
        PCBW  60.0   ; PCB width
        HOLED  3.5   ; mounting-hole diameter (M3 clearance)
        HINS   4.0)  ; hole inset from corner
  (setq PCBX (/ (- L PCBL) 2.0)
        PCBY (/ (- W PCBW) 2.0))

  ;; ---------------------- helper: create/set layer -------------------
  (defun mklay (n c) (command "_.-LAYER" "_M" n "_C" c n "") (princ))
  (mklay "ENCLOSURE" "7")(mklay "PCB" "3")(mklay "COMPONENTS" "5")
  (mklay "HOLES" "1")(mklay "DIM" "8")(mklay "TXT" "2")

  ;; ==================== 3D SOLID ENCLOSURE ============================
  (command "_.-LAYER" "_S" "ENCLOSURE" "")
  ;; outer shell
  (command "_.BOX" "0,0,0"
           (strcat (rtos L) "," (rtos W) "," (rtos H)))
  (setq encl (entlast))
  ;; inner cavity (subtract)
  (command "_.BOX"
           (strcat (rtos WALL) "," (rtos WALL) "," (rtos LID))
           (strcat (rtos (- L WALL)) "," (rtos (- W WALL)) "," (rtos (+ H 1.0))))
  (setq cav (entlast))
  (command "_.SUBTRACT" encl "" cav "")
  (setq encl (entlast))
  ;; four through mounting holes
  (foreach p (list (list HINS HINS) (list (- L HINS) HINS)
                   (list HINS (- W HINS)) (list (- L HINS) (- W HINS)))
    (command "_.CYLINDER"
             (strcat (rtos (car p)) "," (rtos (cadr p)) ",-1")
             (rtos (/ HOLED 2.0)) (rtos (+ H 2.0)))
    (setq cyl (entlast))
    (command "_.SUBTRACT" encl "" cyl "")
    (setq encl (entlast)))
  ;; front-panel connector slot (subtract)
  (command "_.BOX"
           (strcat (rtos (* 0.25 L)) ",-1," (rtos (+ LID 2.0)))
           (strcat (rtos (* 0.55 L)) "," (rtos (+ WALL 1.0)) "," (rtos (+ LID 8.0))))
  (setq cyl (entlast))
  (command "_.SUBTRACT" encl "" cyl "")

  ;; ==================== 2D DIMENSIONED PLAN ==========================
  (setq oy (- (+ W 40.0)))          ; place plan below the 3D model in -Y
  (defun p1 (x y) (list x (+ oy y)))
  ;; enclosure outline
  (command "_.-LAYER" "_S" "ENCLOSURE" "")
  (command "_.RECTANG" (p1 0 0) (p1 L W))
  ;; PCB
  (command "_.-LAYER" "_S" "PCB" "")
  (command "_.RECTANG" (p1 PCBX PCBY) (p1 (+ PCBX PCBL) (+ PCBY PCBW)))
  ;; mounting holes
  (command "_.-LAYER" "_S" "HOLES" "")
  (foreach p (list (list HINS HINS) (list (- L HINS) HINS)
                   (list HINS (- W HINS)) (list (- L HINS) (- W HINS)))
    (command "_.CIRCLE" (p1 (car p) (cadr p)) (rtos (/ HOLED 2.0))))
  ;; component footprints  (x y w h label)
  (command "_.-LAYER" "_S" "COMPONENTS" "")
  (setq comp (list
     (list 11.5 39 20 18 "ESP32-S3")  (list 67 39 16 18 "BLE/WiFi")
     (list 11.5 11 18 12 "INA228")    (list 33 11 16 12 "iso-V")
     (list 51 11 10 10 "Temp")        (list 63 11 18 16 "Relay-drv")))
  (foreach c comp
    (command "_.RECTANG" (p1 (nth 0 c) (nth 1 c))
             (p1 (+ (nth 0 c)(nth 2 c)) (+ (nth 1 c)(nth 3 c))))
    (command "_.-LAYER" "_S" "TXT" "")
    (command "_.TEXT" (p1 (+ (nth 0 c) 1.0) (+ (nth 1 c) 4.0)) "2.0" "0" (nth 4 c))
    (command "_.-LAYER" "_S" "COMPONENTS" ""))
  ;; dimensions
  (command "_.-LAYER" "_S" "DIM" "")
  (command "_.DIMLINEAR" (p1 0 0) (p1 L 0) (p1 (/ L 2.0) -10))
  (command "_.DIMLINEAR" (p1 0 0) (p1 0 W) (p1 -10 (/ W 2.0)))
  (command "_.DIMLINEAR" (p1 HINS W) (p1 (- L HINS) W) (p1 (/ L 2.0) (+ W 12)))
  ;; title
  (command "_.-LAYER" "_S" "TXT" "")
  (command "_.TEXT" (p1 0 -14) "2.4" "0"
           "V-GUARD SENTINEL AI CORE (signal & control) - 90x70x35 mm, ABS UL94 V-0, PCB 80x60 - mounts ON/WITH inverter; battery current via EXTERNAL 500A/50mV shunt or Hall (mV only to PCB) - dims mm")

  (command "_.ZOOM" "_E")
  (princ "\nV-Guard Sentinel AI Core drawn (3D solid + 2D plan). ")
  (princ))
(princ "\nLoaded. Type  SENTINEL  to draw the AI Core enclosure + PCB.")
(princ)
