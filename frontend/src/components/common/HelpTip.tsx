import HelpOutlineOutlined from "@mui/icons-material/HelpOutlineOutlined";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";

/** A small "?" that explains what is next to it. Opens on hover, on keyboard focus and on tap. */
export function HelpTip({ title, text }: { title: string; text: string }) {
  return (
    <Tooltip title={text} describeChild enterTouchDelay={0} leaveTouchDelay={8000}>
      <IconButton size="small" aria-label={`About ${title}`} sx={{ p: 0.25, ml: 0.5, color: "text.secondary", verticalAlign: "middle" }}>
        <HelpOutlineOutlined sx={{ fontSize: 16 }} />
      </IconButton>
    </Tooltip>
  );
}
