import Box from "@mui/material/Box";

/** A contact-sheet frame with a marker loop: the product in one picture. */
export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <Box component="svg" viewBox="0 0 32 32" aria-hidden="true" sx={{ width: size, height: size, flex: "none", display: "block" }}>
      <Box component="rect" x="4" y="6" width="20" height="20" rx="2"
        sx={{ fill: "none", stroke: "var(--mui-palette-text-primary)", strokeWidth: 2.2 }} />
      <Box component="path" d="M24 7c-6-3-15 0-15 9 0 7 6 11 13 9 6-2 8-9 5-14-2-3-6-4-9-3"
        sx={{ fill: "none", stroke: "var(--mui-palette-secondary-main)", strokeWidth: 2.4, strokeLinecap: "round" }} />
    </Box>
  );
}
