import { useSubscription } from "../../api/hooks";
import { errorMessage } from "../../lib/errors";
import { useNotify } from "./notify";

/** What a 🔔 button or menu entry says it does. */
export function followLabel(following: boolean): string {
  return following ? "Stop following (no more DMs)" : "Follow with 🔔 (DM me when it changes)";
}

/**
 * What the 🔔 reaction does, for a button and a long-press menu alike: follow a listing to get a DM
 * when its price, buyout or stock changes, or stop, and say which.
 */
export function useFollow() {
  const notify = useNotify();
  const subscription = useSubscription();
  return {
    toggle: (itemId: string, following: boolean) => subscription.mutate({ itemId, follow: !following }, {
      onSuccess: () => notify(following ? "You no longer get DMs for this listing." : "You get a DM when this listing changes.", "success"),
      onError: (error) => notify(errorMessage(error), "error"),
    }),
    /** The listing being followed or unfollowed, so its button can wait for the answer. */
    pending: subscription.isPending ? subscription.variables?.itemId ?? null : null,
  };
}
