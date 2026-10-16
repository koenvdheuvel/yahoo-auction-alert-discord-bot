import { createTheme } from "@mui/material/styles";

// Discord's own colours, for its dark and its light theme, so the dashboard reads like the app
// the searches post into. The server list, the channel list and the main area each get the
// shade Discord gives them.
declare module "@mui/material/styles" {
  interface Palette {
    surface: Surface;
  }
  interface PaletteOptions {
    surface?: Surface;
  }
}

interface Surface {
  /** The server list on the far left. */
  rail: string;
  /** The channel list. */
  sidebar: string;
  /** The account panel under the channel list. */
  panel: string;
  /** A row the pointer is over, and the selected row. */
  hover: string;
  selected: string;
  /** Channel names that have nothing in them. */
  muted: string;
  /** The small count badges. */
  badge: string;
}

const blurple = "#5865F2";

// Japanese titles fall back to the system's Gothic font; a web font for Japanese would be megabytes.
// "gg sans" is Discord's font; people who have it installed see the same letters as in Discord.
const fontFamily = [
  '"gg sans"', '"Noto Sans"', '"Hiragino Sans"', '"Hiragino Kaku Gothic ProN"', '"Yu Gothic UI"', "Meiryo",
  '"Noto Sans JP"', '"Helvetica Neue"', "Helvetica", "Arial", "system-ui", "sans-serif",
].join(", ");

/** Even-width figures for prices, counts and dates. */
export const figures = { fontVariantNumeric: "tabular-nums" } as const;
/** The alert's name in headings. Kept for components that ask for a wider look. */
export const wide = { letterSpacing: "-0.005em" } as const;
export const mono = 'ui-monospace, "SF Mono", Menlo, Consolas, monospace';
/** Widths of the server list and the channel list. */
export const RAIL_WIDTH = 72;
export const SIDEBAR_WIDTH = 240;
export const TOPBAR_HEIGHT = 48;

export const theme = createTheme({
  cssVariables: { colorSchemeSelector: "data" },
  colorSchemes: {
    dark: {
      palette: {
        primary: { main: blurple, contrastText: "#FFFFFF" },
        // The operator's labels are drawn in red; Discord's red for danger is the same family.
        secondary: { main: "#F23F43", contrastText: "#FFFFFF" },
        success: { main: "#23A55A" },
        warning: { main: "#F0B232" },
        error: { main: "#F23F43" },
        info: { main: "#00A8FC" },
        background: { default: "#313338", paper: "#2B2D31" },
        text: { primary: "#DBDEE1", secondary: "#B5BAC1", disabled: "#80848E" },
        divider: "#3F4147",
        surface: { rail: "#1E1F22", sidebar: "#2B2D31", panel: "#232428", hover: "#35373C", selected: "#404249",
          muted: "#80848E", badge: "#F23F43" },
      },
    },
    light: {
      palette: {
        primary: { main: blurple, contrastText: "#FFFFFF" },
        secondary: { main: "#DA373C", contrastText: "#FFFFFF" },
        success: { main: "#248046" },
        warning: { main: "#B56A00" },
        error: { main: "#DA373C" },
        info: { main: "#006CE7" },
        background: { default: "#FFFFFF", paper: "#F2F3F5" },
        text: { primary: "#313338", secondary: "#4E5058", disabled: "#80848E" },
        divider: "#E1E2E4",
        surface: { rail: "#E3E5E8", sidebar: "#F2F3F5", panel: "#EBEDEF", hover: "#E0E1E5", selected: "#D4D7DC",
          muted: "#5C5E66", badge: "#DA373C" },
      },
    },
  },
  shape: { borderRadius: 4 },
  typography: {
    fontFamily,
    fontSize: 14,
    h1: { fontSize: "1.375rem", lineHeight: 1.2, fontWeight: 700 },
    h2: { fontSize: "1rem", lineHeight: 1.3, fontWeight: 700 },
    h3: { fontSize: "0.9375rem", lineHeight: 1.35, fontWeight: 650 },
    subtitle1: { fontSize: "0.9375rem", fontWeight: 600 },
    subtitle2: { fontSize: "0.8125rem", fontWeight: 600 },
    body1: { fontSize: "0.875rem", lineHeight: 1.45 },
    body2: { fontSize: "0.8125rem", lineHeight: 1.4 },
    caption: { fontSize: "0.75rem", lineHeight: 1.35 },
    overline: { fontSize: "0.75rem", fontWeight: 700, letterSpacing: "0.02em", lineHeight: 1.3 },
    button: { textTransform: "none", fontWeight: 600, letterSpacing: 0 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: (theme) => ({
        body: { WebkitFontSmoothing: "antialiased" },
        // Ripples are off, so keyboard focus gets a plain outline on every control.
        ".Mui-focusVisible, a:focus-visible": {
          outline: `2px solid ${theme.vars.palette.info.main}`,
          outlineOffset: 2,
          zIndex: 1,
        },
        "@media (prefers-reduced-motion: reduce)": {
          "*, *::before, *::after": { animationDuration: "0.01ms !important", transitionDuration: "0.01ms !important" },
        },
      }),
    },
    MuiButtonBase: { defaultProps: { disableRipple: true } },
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { borderRadius: 3 } } },
    MuiToggleButton: { styleOverrides: { root: { textTransform: "none" } } },
    // Subtitles are emphasis, not headings; real headings pass `component` explicitly.
    MuiTypography: { defaultProps: { variantMapping: { subtitle1: "p", subtitle2: "p" } } },
    MuiPaper: { defaultProps: { elevation: 0 } },
    MuiAppBar: { defaultProps: { elevation: 0, color: "inherit" } },
    MuiTooltip: { defaultProps: { enterDelay: 300, enterNextDelay: 150 } },
    MuiChip: { defaultProps: { size: "small" }, styleOverrides: { root: { borderRadius: 4, fontWeight: 600 } } },
    MuiTextField: { defaultProps: { size: "small" } },
    MuiSelect: { defaultProps: { size: "small" } },
    MuiTab: {
      styleOverrides: {
        root: { textTransform: "none", minHeight: 40, fontWeight: 600, fontSize: "0.875rem", paddingInline: 12 },
      },
    },
    MuiTabs: { styleOverrides: { root: { minHeight: 40 } } },
    MuiLink: { defaultProps: { underline: "hover", color: "info" } },
    // Discord's dialogs and menus are flat: no lighter overlay on dark backgrounds.
    MuiDialog: {
      defaultProps: { fullWidth: true },
      styleOverrides: { paper: ({ theme }) => ({ backgroundImage: "none", backgroundColor: theme.vars.palette.background.default }) },
    },
    MuiMenu: { styleOverrides: { paper: ({ theme }) => ({ backgroundImage: "none", backgroundColor: theme.vars.palette.surface.panel }) } },
    MuiPopover: { styleOverrides: { paper: { backgroundImage: "none" } } },
    MuiDrawer: { styleOverrides: { paper: { backgroundImage: "none" } } },
    MuiTableCell: { styleOverrides: { root: { paddingBlock: 6 } } },
    MuiListItemButton: { styleOverrides: { root: { borderRadius: 4 } } },
  },
});
