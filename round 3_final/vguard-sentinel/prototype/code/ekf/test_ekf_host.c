/* ekf/test_ekf_host.c -- host test harness for the C EKF port.
 *
 * Reads a CSV produced by ekf/sim_battery_for_ekf.py (columns per
 * CONTRACTS.md §1 plus charger_on: t,I,V,T,grid,P_load,soc_true,soh_true,
 * charger_on), runs ekf_step() over every row, and writes a SoC trace CSV
 * (t,soc,r0_ohm) so tests/test_ekf.py can diff it against the Python EKF's
 * own trace on the same input (CONTRACTS §6 API; no malloc, no printf in
 * ekf.c itself -- this harness is the only place output happens).
 *
 * Usage: ekf_test_host <input_csv> <output_csv> [q_rated_ah]
 *
 * Sign convention: the CSV's I column is +charge/-discharge (CONTRACTS §1);
 * ekf_step wants discharge-positive (CONTRACTS §6), so this harness flips
 * the sign at the boundary -- exactly what real firmware glue must also do.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ekf.h"

#define MAX_LINE 1024

int main(int argc, char** argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: %s <input_csv> <output_csv> [q_rated_ah]\n", argv[0]);
        return 2;
    }
    const char* in_path = argv[1];
    const char* out_path = argv[2];
    float q_rated_ah = (argc >= 4) ? (float)atof(argv[3]) : 150.0f;

    FILE* fin = fopen(in_path, "r");
    if (!fin) { fprintf(stderr, "cannot open %s\n", in_path); return 1; }
    FILE* fout = fopen(out_path, "w");
    if (!fout) { fprintf(stderr, "cannot open %s\n", out_path); fclose(fin); return 1; }

    char line[MAX_LINE];
    if (!fgets(line, sizeof(line), fin)) { fprintf(stderr, "empty input\n"); return 1; }

    /* header: t,I,V,T,grid,P_load,soc_true,soh_true,charger_on */
    char* col_names[16];
    int ncols = 0;
    {
        char hdr[MAX_LINE];
        strncpy(hdr, line, sizeof(hdr) - 1);
        hdr[sizeof(hdr) - 1] = '\0';
        char* tok = strtok(hdr, ",\r\n");
        while (tok && ncols < 16) { col_names[ncols++] = tok; tok = strtok(NULL, ",\r\n"); }
    }
    int idx_t = -1, idx_I = -1, idx_V = -1, idx_T = -1, idx_charger = -1;
    for (int i = 0; i < ncols; i++) {
        if (strcmp(col_names[i], "t") == 0) idx_t = i;
        else if (strcmp(col_names[i], "I") == 0) idx_I = i;
        else if (strcmp(col_names[i], "V") == 0) idx_V = i;
        else if (strcmp(col_names[i], "T") == 0) idx_T = i;
        else if (strcmp(col_names[i], "charger_on") == 0) idx_charger = i;
    }
    if (idx_I < 0 || idx_V < 0 || idx_T < 0 || idx_charger < 0) {
        fprintf(stderr, "input CSV missing required columns (I,V,T,charger_on)\n");
        return 1;
    }

    ekf_params_t params;
    ekf_params_default(&params, q_rated_ah);
    ekf_t e;
    ekf_init(&e, &params);

    fprintf(fout, "t,soc,r0_ohm,v1\n");

    long row_t = 0;
    while (fgets(line, sizeof(line), fin)) {
        char* fields[16];
        int nf = 0;
        char* tok = strtok(line, ",\r\n");
        while (tok && nf < 16) { fields[nf++] = tok; tok = strtok(NULL, ",\r\n"); }
        if (nf <= idx_charger) continue;

        float I_charge_pos = (float)atof(fields[idx_I]);
        float V = (float)atof(fields[idx_V]);
        float T = (float)atof(fields[idx_T]);
        int charger_on = atoi(fields[idx_charger]);
        if (fields[idx_charger][0] == 'T' || fields[idx_charger][0] == 't') charger_on = 1;
        if (fields[idx_charger][0] == 'F' || fields[idx_charger][0] == 'f') charger_on = 0;

        float I_discharge_pos = -I_charge_pos; /* CONTRACTS §1 -> §6 boundary flip */
        ekf_step(&e, I_discharge_pos, V, T, charger_on);

        if (idx_t >= 0 && nf > idx_t) {
            fprintf(fout, "%s,%.6f,%.6f,%.6f\n", fields[idx_t], ekf_soc(&e), ekf_r0(&e), ekf_v1(&e));
        } else {
            fprintf(fout, "%ld,%.6f,%.6f,%.6f\n", row_t, ekf_soc(&e), ekf_r0(&e), ekf_v1(&e));
        }
        row_t++;
    }

    fclose(fin);
    fclose(fout);
    return 0;
}
