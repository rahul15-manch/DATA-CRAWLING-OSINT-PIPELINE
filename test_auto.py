import subprocess

if __name__ == "__main__":
    print("Running pipeline for: 'software companies gurgaon'")
    subprocess.run(
        ["python", "run_pipeline.py"],
        input="software companies gurgaon\n",
        text=True,
        check=False
    )
    print("Done!")
