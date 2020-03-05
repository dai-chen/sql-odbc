"""
 *   Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
 *
 *   Licensed under the Apache License, Version 2.0 (the "License").
 *   You may not use this file except in compliance with the License.
 *	 A copy of the License is located at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *   or in the "license" file accompanying this file. This file is distributed
 *   on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
 *   express or implied. See the License for the specific language governing
 *   permissions and limitations under the License.
"""

import os
import subprocess
import json
import re
import traceback
import sys
import getopt
import shutil
from mako.template import Template

UT_TYPE = "UT"
IT_TYPE = "IT"
EXCLUDE_EXTENSION_LIST = (".log", ".pdb", ".dll")
total_failures = 0

def GetTestSuiteExes(test_type, test_suites, exclude_tests_list):
    if test_type != UT_TYPE and test_type != IT_TYPE:
        return []
    test_exes = []
    for root, dirs, files in os.walk(os.getcwd()):
        for name in dirs:
            if name.startswith("bin"):
                dirs = name
        for file_name in files:
            if file_name.endswith(EXCLUDE_EXTENSION_LIST):
                continue
            if file_name.startswith(tuple(exclude_tests_list)):
                print(f"Skipping test {file_name}, because it is in test exclude list.")
                continue
            if test_suites is None and file_name.startswith(test_type.lower()):
                print(f"Found {test_type} file: {file_name}")
                test_exes.append(os.path.join(root, file_name))
            elif test_suites is not None and file_name.startswith(test_type.lower()) and (file_name in test_suites.split(sep=",")):
                print(f"Found {test_type} file: {file_name}")
                test_exes.append(os.path.join(root, file_name))
    return test_exes

def RunTests(tests, test_type):
    output = []
    global total_failures
    for test in tests:
        print("Running " + test)
        output_path = test.replace(".exe", "") + ".log"
        total_failures += subprocess.call([test, "-fout", output_path, "--gtest_color=no"])
        if test_type == UT_TYPE:
            with open(output_path, "r+") as f:
                output.append({"UnitTest" : test.split(os.path.sep)[-1].replace(".exe",""), "Log": f.read()})
        elif test_type == IT_TYPE:
            # TODO: Fix this so it works for integration tests
            with open(output_path, "r+") as f:
                output.append({"IntegrationTest" : test.split(os.path.sep)[-1].replace(".exe",""), "Log": f.read()})
    print("Total Failures :", total_failures)
    return output

def FindBetween(s, f, l):
    try:
        start = s.index(f) + len(f)
        end = s.index(l,start)
        return s[start:end]
    except ValueError:
        return ""

def ParseUnitTestCase(log_lines, test_case):
    start_tag = test_case + "." 
    test_case_info = { "TestCase" : test_case }
    tests = []
    for log_line in log_lines:
        if start_tag in log_line and "RUN" in log_line:
            test = log_line.split(start_tag)[1]
            tests.append(test)
        if "[----------] " in log_line and (test_case + " ") in log_line and log_line.endswith(" ms total)"):
            test_case_info["TotalTime"] = FindBetween(log_line, "(", ")").replace(" total","")

    test_infos = []
    for test in tests:
        test_tag = start_tag + test
        test_info = { "TestName" : test }
        for log_line in log_lines:
            if test_tag in log_line and log_line.endswith(")"):
                test_info["TestTime"] = FindBetween(log_line, "(", ")")
                test_info["TestResult"] = FindBetween(log_line, "[", "]").replace(" ", "")

        if test_info["TestResult"] != "OK":
            start_error_grab = False
            error_info = ""
            for log_line in log_lines:
                if test_tag in log_line and not log_line.endswith(")"):
                    start_error_grab = True
                elif test_tag in log_line and log_line.endswith(")"):
                    break
                elif start_error_grab:
                    if error_info != "":
                        error_info += os.linesep + log_line
                    else:
                        error_info += log_line
            test_info["Error"] = error_info
        test_infos.append(test_info)
    test_case_info["TestCount"] = str(len(test_infos))
    test_case_info["TestResults"] = test_infos
    pass_count = 0
    for test_info in test_infos:
        if test_info["TestResult"] == "OK":
            pass_count = pass_count + 1
    test_case_info["PassCount"] = str(pass_count)
    return test_case_info
    
def ParseUnitTestLog(unit_test, log):
    log_json = { "UnitTest" : unit_test }
    log_split = log.splitlines()
    if len(log) < 8:
        return {}

    tmp = ""
    for log in log_split:
        if log.startswith("[==========] Running"):
                #           [==========] Running 16 tests from 8 test cases.
            tmp = log.replace("[==========] Running ", "").replace(" test cases.", "").replace(" test case.", "").replace("tests from", "").replace("test from", "")
    if tmp == "":
        print('FAILED TO FIND LOG WITH RUNNING')
    print("SPLIT: " + str(tmp.split("  ")))
    log_json["TotalTestCount"] = tmp.split("  ")[0]
    log_json["TotalTestCases"] = tmp.split("  ")[1]
    log_json["TestCases"] = []
    test_cases = []
    for _line in log_split:
        tag = { }
        if re.match(r".*tests? from.*", _line) and "[----------]" in _line and "total" not in _line:
            test_cases.append(re.split(" tests? from ", _line)[1])
    case_pass_count = 0
    test_pass_count = 0
    for test_case in test_cases:
        log_json["TestCases"].append(ParseUnitTestCase(log_split, test_case))
    for test_case in log_json["TestCases"]:
        if test_case["PassCount"] == test_case["TestCount"]:
            case_pass_count += 1
        test_pass_count += int(test_case["PassCount"])
    log_json["CasePassCount"] = str(case_pass_count)
    log_json["TestPassCount"] = str(test_pass_count)
    return log_json

def TranslateTestOutput(test_type, outputs):
    log_jsons = []
    if test_type == UT_TYPE:
        for output in outputs:
            log_jsons.append(ParseUnitTestLog(output["UnitTest"], output["Log"]))
    elif test_type == IT_TYPE:
        for output in outputs:
            log_jsons.append(ParseUnitTestLog(output["IntegrationTest"], output["Log"]))
    return log_jsons

def RunAllTests(test_types, test_suites, exclude_test_list):
    final_output = {}

    for _type in test_types:
        tests = GetTestSuiteExes(_type, test_suites, exclude_test_list)
        print("!! Found tests:", *tests, sep="\n")
        test_outputs = RunTests(tests, _type)
        print("======== Translating output ==========")
        final_output[_type] = TranslateTestOutput(_type, test_outputs)
        print("======== Finished translatiing ==========")
    print("======== Finished all translations ==========")
    return final_output

def ParseCommandLineArguments():
    infile = None
    outfile = None
    suites = None
    efile = None
    opts, args = getopt.getopt(sys.argv[1:],"i:o:s:e:",["ifile=","ofile=","suites=","efile="])
    for opt,arg in opts:
        if opt in ('-i', '--ifile'):
            infile = arg
        elif opt in ('-s', '--suites'):
            suites = arg
        elif opt in ('-o', '--ofile'):
            outfile = arg
        elif opt in ('-e', '--efile'):
            efile = arg
    return (infile, outfile, suites, efile)

def main():
    try:
        (infile, outfile, suites, efile) = ParseCommandLineArguments()
        if infile is None or outfile is None:
            print("Usage: -i <infile> -o <outfile> [-s <test_suites> -e <efile>]")
            sys.exit(1)
        exclude_test_list = []
        if efile is not None:
            with open(efile) as ef:
                exclude_test_list = ef.readlines()
                exclude_test_list = [l.strip() for l in exclude_test_list if l.strip() != ""]
            if len(exclude_test_list) == 0:
                print('== Exclude list empty. Running all available tests ==')
            else:
                print(f'== Excluding tests {exclude_test_list} ==')
        else:
            print('== No exclude list. Running all available tests ==')
        print(f'== Using template file {infile} ==')
        template = Template(filename=infile)

        if suites is not None: 
            print(f'== Using suites {suites} ==')
        full_path_outfile = os.path.join(os.getcwd(), outfile)
        with open(full_path_outfile, 'w+') as results_file:
            data = RunAllTests([UT_TYPE, IT_TYPE], suites, exclude_test_list)
            print('== done test running ==')
            os.chmod(outfile, 0o744)
            print('== rendering output ==')
            results_file.write(template.render(data = data))

        print(f"== Finished generating results file {full_path_outfile} ==")

        os._exit(total_failures)

    except:
        print(traceback.format_exc())
        sys.exit(255)

if __name__ == "__main__":
    main()