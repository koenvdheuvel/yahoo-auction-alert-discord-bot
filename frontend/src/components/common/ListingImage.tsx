import ImageNotSupportedOutlined from "@mui/icons-material/ImageNotSupportedOutlined";
import Box from "@mui/material/Box";
import { useState } from "react";

import { safeUrl } from "../../lib/format";

interface Props {
  src: string | null | undefined;
  /** CSS aspect ratio of the frame, such as "1" or "4 / 3". */
  ratio?: string;
  size?: number | string;
}

/** A marketplace photo. Sent without a referrer; a missing photo shows a plain placeholder. */
export function ListingImage({ src, ratio = "1", size = "100%" }: Props) {
  const url = safeUrl(src);
  const [failed, setFailed] = useState<string | null>(null);
  const broken = !url || failed === url;
  return (
    <Box sx={{ width: size, aspectRatio: ratio, bgcolor: "action.hover", display: "grid", placeItems: "center",
      overflow: "hidden", flex: "none" }}>
      {broken ? (
        <ImageNotSupportedOutlined sx={{ color: "text.disabled" }} titleAccess={url ? "Photo unavailable" : "No photo saved"} />
      ) : (
        <Box component="img" src={url} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer"
          onError={() => setFailed(url)} sx={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }} />
      )}
    </Box>
  );
}
