# install.packages("sensobol")
library(sensobol)
library(data.table)

# ── Settings ───────────────────────────────────────────────────────────────────
N      <- 100          # base sample size — increase for better convergence
params <- c("density") # input parameters (expand later e.g. c("density","porosity"))
R_boot <- 1000         # bootstrap replicas for confidence intervals

# Apophis bulk density range in kg/m^3
# Literature range: ~1400 (low, very porous) to ~3500 (high, rocky)
DENSITY_MIN <- 1400
DENSITY_MAX <- 3500

# ── Generate Sobol sample matrix ───────────────────────────────────────────────
# This creates the A, B, and AB matrices needed for Sobol indices
# type = "QRN" uses quasi-random Sobol sequences (better coverage than LHS)
mat <- sobol_matrices(N = N, params = params, type = "QRN")

# mat is in [0,1] — rescale to your physical density range
mat_scaled <- mat
mat_scaled[, "density"] <- qunif(mat[, "density"],
                                  min = DENSITY_MIN,
                                  max = DENSITY_MAX)

# Each row is one PHANTOM run. Total rows = N * (k + 2) = 100 * 3 = 300
cat("Total PHANTOM runs required:", nrow(mat_scaled), "\n")

# Save to CSV so bash can read it
args <- commandArgs(trailingOnly = FALSE)
file_arg <- "--file="
script_path <- sub(file_arg, "", args[grep(paste0("^", file_arg), args)])[1]
if (is.na(script_path) || !nzchar(script_path)) {
  # When run via source("..."), pick up the sourced file path.
  script_path <- tryCatch(normalizePath(sys.frames()[[1]]$ofile, winslash = "/", mustWork = FALSE),
                          error = function(e) NA_character_)
}
if (is.na(script_path) || !nzchar(script_path)) {
  # Final fallback for interactive runs in IDE/console.
  script_dir <- getwd()
} else {
  script_dir <- dirname(normalizePath(script_path, winslash = "/", mustWork = FALSE))
}
out_file <- file.path(script_dir, "sobol_input_matrix.csv")
fwrite(data.table(run_id = 1:nrow(mat_scaled), mat_scaled), out_file)
cat("Saved Sobol matrix to:", normalizePath(out_file, winslash = "/", mustWork = FALSE), "\n")