import Campaign from "@mui/icons-material/Campaign";
import ForumOutlined from "@mui/icons-material/ForumOutlined";
import LockOutlined from "@mui/icons-material/LockOutlined";
import Podcasts from "@mui/icons-material/Podcasts";
import SubdirectoryArrowRight from "@mui/icons-material/SubdirectoryArrowRight";
import Tag from "@mui/icons-material/Tag";
import VolumeUp from "@mui/icons-material/VolumeUp";
import type { SvgIconProps } from "@mui/material/SvgIcon";

import type { ChannelKind } from "../../api/types";

/** The icon Discord's sidebar shows for a kind of channel. */
export function ChannelIcon({ kind, ...props }: { kind: ChannelKind } & SvgIconProps) {
  const sx = { fontSize: 18, flex: "none", ...props.sx };
  switch (kind) {
    case "announcement":
      return <Campaign {...props} sx={sx} />;
    case "forum":
    case "media":
      return <ForumOutlined {...props} sx={sx} />;
    case "voice":
      return <VolumeUp {...props} sx={sx} />;
    case "stage":
      return <Podcasts {...props} sx={sx} />;
    case "thread":
      return <SubdirectoryArrowRight {...props} sx={sx} />;
    case "private_thread":
      return <LockOutlined {...props} sx={sx} />;
    default:
      return <Tag {...props} sx={sx} />;
  }
}
