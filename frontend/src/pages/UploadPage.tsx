import { Upload } from "lucide-react";

import { PlaceholderPage } from "@/components/PlaceholderPage";

export function UploadPage() {
  return (
    <PlaceholderPage
      title="Upload lecture"
      description="Drag and drop an MP3, WAV, MP4 or M4A recording."
      phase={8}
      icon={Upload}
    />
  );
}
