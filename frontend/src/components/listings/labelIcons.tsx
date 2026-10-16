import Close from "@mui/icons-material/Close";
import ExtensionOutlined from "@mui/icons-material/ExtensionOutlined";
import LayersOutlined from "@mui/icons-material/LayersOutlined";
import QuestionMark from "@mui/icons-material/QuestionMark";
import RadioButtonUnchecked from "@mui/icons-material/RadioButtonUnchecked";
import type { ReactElement } from "react";

import type { Label } from "../../api/types";

export const LABEL_ICONS: Record<Label, ReactElement> = {
  relevant: <RadioButtonUnchecked fontSize="inherit" />,
  wrong_product: <Close fontSize="inherit" />,
  accessory: <ExtensionOutlined fontSize="inherit" />,
  bundle: <LayersOutlined fontSize="inherit" />,
  unsure: <QuestionMark fontSize="inherit" />,
};
