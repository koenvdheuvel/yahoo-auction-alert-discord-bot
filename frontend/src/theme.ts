import { createTheme } from "@mui/material/styles";

// Contact sheet and china marker: the bot's decisions are printed in quiet inks, the
// operator's labels are drawn in marker red (palette.secondary). Nothing else uses red.
const ink = "#1C2128";
const graphite = "#59616E";

// Japanese titles fall back to the system's Gothic font; a web font for Japanese would be megabytes.
const fontFamily = [
  '"Archivo Variable"', '"Hiragino Sans"', '"Hiragino Kaku Gothic ProN"', '"Yu Gothic UI"', "Meiryo",
  '"Noto Sans JP"', '"Noto Sans CJK JP"', "system-ui", "sans-serif",
].join(", ");

/** Narrow, even-width figures for prices, counts and dates. */
export const figures = { fontStretch: "84%", fontVariantNumeric: "tabular-nums" } as const;
/** The wide face used for the alert's name. */
export const wide = { fontStretch: "114%" } as const;
export const mono = 'ui-monospace, "SF Mono", Menlo, Consolas, monospace';

export const theme = createTheme({
  cssVariables: { colorSchemeSelector: "data" },
  colorSchemes: {
    light: {
      palette: {
        primary: { main: ink, contrastText: "#FFFFFF" },
        secondary: { main: "#D7263D", contrastText: "#FFFFFF" },
        success: { main: "#1F7A55" },
        warning: { main: "#A86200" },
        error: { main: "#B3261E" },
        info: { main: "#2E5AAC" },
        background: { default: "#F3F4F5", paper: "#FFFFFF" },
        text: { primary: ink, secondary: graphite },
        divider: "#D8DCE1",
      },
    },
    dark: {
      palette: {
        primary: { main: "#E7EAEE", contrastText: "#121417" },
        secondary: { main: "#FF5468", contrastText: "#121417" },
        success: { main: "#4CC38A" },
        warning: { main: "#E5A13A" },
        error: { main: "#FF6B6B" },
        info: { main: "#7AA7FF" },
        background: { default: "#121417", paper: "#1A1D21" },
        text: { primary: "#E7EAEE", secondary: "#9AA3AE" },
        divider: "#2C3138",
      },
    },
  },
  shape: { borderRadius: 6 },
  typography: {
    fontFamily,
    fontSize: 14,
    h1: { fontSize: "1.65rem", lineHeight: 1.15, fontWeight: 680, letterSpacing: "-0.01em", ...wide },
    h2: { fontSize: "1.125rem", lineHeight: 1.3, fontWeight: 650, ...wide },
    h3: { fontSize: "0.95rem", lineHeight: 1.35, fontWeight: 650 },
    subtitle1: { fontSize: "0.95rem", fontWeight: 600 },
    subtitle2: { fontSize: "0.8125rem", fontWeight: 600 },
    body1: { fontSize: "0.875rem", lineHeight: 1.5 },
    body2: { fontSize: "0.8125rem", lineHeight: 1.45 },
    caption: { fontSize: "0.75rem", lineHeight: 1.4 },
    button: { textTransform: "none", fontWeight: 600, letterSpacing: 0 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: (theme) => ({
        body: { WebkitFontSmoothing: "antialiased" },
        // Ripples are off, so keyboard focus gets a plain outline on every control.
        ".Mui-focusVisible, a:focus-visible": {
          outline: `2px solid ${theme.vars.palette.text.primary}`,
          outlineOffset: 2,
          zIndex: 1,
        },
        "@media (prefers-reduced-motion: reduce)": {
          "*, *::before, *::after": { animationDuration: "0.01ms !important", transitionDuration: "0.01ms !important" },
        },
      }),
    },
    MuiButtonBase: { defaultProps: { disableRipple: true } },
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiToggleButton: { styleOverrides: { root: { textTransform: "none" } } },
    // Subtitles are emphasis, not headings; real headings pass `component` explicitly.
    MuiTypography: { defaultProps: { variantMapping: { subtitle1: "p", subtitle2: "p" } } },
    MuiPaper: { defaultProps: { elevation: 0 } },
    MuiAppBar: { defaultProps: { elevation: 0, color: "inherit" } },
    MuiTooltip: { defaultProps: { enterDelay: 400, enterNextDelay: 200 } },
    MuiChip: { defaultProps: { size: "small" } },
    MuiTextField: { defaultProps: { size: "small" } },
    MuiSelect: { defaultProps: { size: "small" } },
    MuiTab: {
      styleOverrides: {
        root: { textTransform: "none", minHeight: 44, fontWeight: 600, fontSize: "0.875rem", paddingInline: 14 },
      },
    },
    MuiTabs: { styleOverrides: { root: { minHeight: 44 } } },
    MuiLink: { defaultProps: { underline: "hover", color: "inherit" } },
    MuiDialog: { defaultProps: { fullWidth: true } },
    MuiTableCell: { styleOverrides: { root: { paddingBlock: 8 } } },
  },
});
