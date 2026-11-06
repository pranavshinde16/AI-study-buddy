import { Loader } from "lucide-react";

import { PlaceholderPage } from "@/components/PlaceholderPage";

export function ProcessingPage() {
  return (
    <PlaceholderPage
      title="Processing lecture"
      description="Stage-by-stage progress: extracting audio, transcribing, indexing, generating."
      phase={8}
      icon={Loader}
    />
  );
}
