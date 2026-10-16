import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Typography from "@mui/material/Typography";

import type { Ruleset } from "../../api/types";
import { METHODS, POLICIES } from "../../lib/vocabulary";
import { mono } from "../../theme";

export function RulesetSummary({ ruleset }: { ruleset: Ruleset }) {
  if (!ruleset.groups.length) {
    return <Typography variant="body2" color="text.secondary">No groups: only the marketplace, price and Discord filter settings apply.</Typography>;
  }
  return (
    <Box component="dl" sx={{ m: 0, display: "grid", gridTemplateColumns: { sm: "minmax(140px, max-content) 1fr" }, columnGap: 2, rowGap: 1 }}>
      {ruleset.groups.map((group) => (
        <Box key={group.id} sx={{ display: "contents" }}>
          <Box component="dt">
            <Typography variant="body2" sx={{ fontWeight: 600 }}>{group.label}</Typography>
            <Typography variant="caption" color="text.secondary">
              {POLICIES[group.policy].name}, {group.match === "all" ? "all terms" : "any term"}
              {group.normalize ? "" : ", original title"}
            </Typography>
          </Box>
          <Box component="dd" sx={{ m: 0, display: "flex", flexWrap: "wrap", gap: 0.5, alignContent: "flex-start" }}>
            {group.terms.map((term, index) => (
              <Chip key={`${term.value}-${index}`} variant="outlined"
                label={term.method === "contains" ? term.value : `${METHODS[term.method].name}: ${term.value}`}
                sx={term.method === "regex" ? { fontFamily: mono, fontSize: "0.75rem" } : undefined} />
            ))}
          </Box>
        </Box>
      ))}
    </Box>
  );
}
